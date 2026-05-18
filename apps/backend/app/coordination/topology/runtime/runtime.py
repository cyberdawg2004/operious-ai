"""`CoordinationTopologyRuntime` — apex topology-structural evaluator.

One public method (`evaluate`) drives one topology evaluation end-
to-end:

    CoordinationTopologyRuntime.evaluate(request)
        → resolve evaluator chain (sorted-name order)
        → for each evaluator: invoke under defensive try/except,
                              collect findings
        → aggregate findings → apex decision + matched edge/path
        → build result + trace
        → persist record
        → return envelope

The runtime is the **single** producer of
`CoordinationTopologyEnvelope`. It NEVER raises — every failure
mode lands on the envelope.

What the runtime DOES NOT do (Sprint L3 final directive):

* dispatch messages,
* reroute coordination,
* invoke coordination policy,
* invoke governance,
* execute agents,
* invoke tools,
* retry execution,
* mutate registries,
* mutate the declared topology.

The runtime composes with the `CoordinationRuntime` via injection
(Sprint L3 Phase 5): the coordination runtime calls `evaluate()`
*before* invoking policy. The two substrates remain isolated; this
runtime never touches policy or governance directly.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from app.identity import (
    AuthorityResolution,
    request_authority_resolution,
)
from app.coordination.topology.contracts.requests import (
    CoordinationTopologyEvaluationRequest,
)
from app.coordination.topology.contracts.results import (
    CoordinationTopologyEvaluationResult,
)
from app.coordination.topology.envelopes import (
    CoordinationTopologyEnvelope,
)
from app.coordination.topology.enums import (
    CoordinationTopologyDecision,
)
from app.coordination.topology.evaluators.base import (
    BaseCoordinationTopologyEvaluator,
)
from app.coordination.topology.exceptions import (
    CoordinationTopologyConfigurationError,
    CoordinationTopologyPersistenceError,
)
from app.coordination.topology.identity import (
    CoordinationTopologyChainId,
    CoordinationTopologyEvaluationId,
    derive_chain_id,
    generate_evaluation_id,
)
from app.coordination.topology.models.findings import (
    CoordinationTopologyFinding,
)
from app.coordination.topology.models.topology import (
    CoordinationTopology,
)
from app.coordination.topology.persistence.repository import (
    CoordinationTopologyPersistenceProtocol,
)
from app.coordination.topology.persistence.serializers import (
    result_to_record,
)
from app.coordination.topology.registry.registry import (
    CoordinationTopologyRegistry,
)
from app.coordination.topology.runtime.aggregator import (
    build_topology_decision,
)
from app.coordination.topology.taxonomy import (
    CoordinationTopologyMetadataKey,
)
from app.coordination.topology.tracing import (
    CoordinationTopologyTrace,
)
from app.observability.context import get_request_id


class CoordinationTopologyRuntime:
    """Apex coordination-topology evaluator. Produces one envelope per call."""

    def __init__(
        self,
        *,
        topology: CoordinationTopology,
        registry: CoordinationTopologyRegistry,
        persistence: CoordinationTopologyPersistenceProtocol,
        chain_id_override: CoordinationTopologyChainId | None = None,
    ) -> None:
        if len(registry) == 0:
            raise CoordinationTopologyConfigurationError(
                "CoordinationTopologyRuntime requires at least one "
                "registered evaluator"
            )
        self._topology = topology
        self._registry = registry
        self._persistence = persistence
        # Chain id derives from sorted evaluator names — same
        # composition ⇒ same chain id across processes / replays.
        self._chain_id: CoordinationTopologyChainId = (
            chain_id_override
            if chain_id_override is not None
            else derive_chain_id(evaluator_names=registry.names())
        )
        self._instance_id: uuid.UUID = uuid.uuid4()
        self._sequence: int = 0
        self._lock = asyncio.Lock()

    # ─── Inspection helpers ──────────────────────────────────────────

    @property
    def runtime_instance_id(self) -> uuid.UUID:
        return self._instance_id

    @property
    def chain_id(self) -> CoordinationTopologyChainId:
        return self._chain_id

    @property
    def topology(self) -> CoordinationTopology:
        return self._topology

    def known_evaluators(self) -> tuple[str, ...]:
        return self._registry.names()

    # ─── Public API ───────────────────────────────────────────────────

    async def evaluate(
        self, request: CoordinationTopologyEvaluationRequest
    ) -> CoordinationTopologyEnvelope:
        """Run one topology evaluation end-to-end. Never raises."""
        loop = asyncio.get_event_loop()
        started_at = datetime.now(timezone.utc)
        loop_start = loop.time()
        # P2-A: singular authority resolution.
        resolution = request_authority_resolution(request)
        evaluation_id = (
            request.evaluation_id_override or generate_evaluation_id()
        )
        request_id = request.request_id or get_request_id()

        # Resolve evaluator subset (sorted-name order).
        try:
            evaluators = self._resolve_evaluators(request.evaluator_names)
        except CoordinationTopologyConfigurationError as exc:
            return self._fail_fast(
                evaluation_id=evaluation_id,
                request=request,
                resolution=resolution,
                request_id=request_id,
                started_at=started_at,
                loop_start=loop_start,
                error=exc,
            )

        # Run evaluators defensively.
        findings: list[CoordinationTopologyFinding] = []
        evaluator_names: list[str] = []
        framework_error: BaseException | None = None
        for evaluator in evaluators:
            evaluator_names.append(evaluator.name)
            try:
                emitted = await evaluator.evaluate(request)
            except Exception as exc:  # noqa: BLE001 — substrate never re-raises
                framework_error = exc
                # Continue collecting findings from other evaluators —
                # Sprint L3 inspectability requirement.
                continue
            findings.extend(emitted)

        apex, matched_edge_id, matched_path_id, reason = (
            build_topology_decision(findings)
        )

        # 2.5-D: lock-split. Sequence assignment is atomic; result
        # construction and persistence run outside the lock so I/O
        # latency does not throttle concurrent evaluators. Persistence
        # failure burns the assigned sequence (no contiguity invariant
        # on topology evaluations).
        async with self._lock:
            self._sequence += 1
            sequence = self._sequence
        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000.0, 3)

        metadata: dict[str, object] = dict(request.metadata)
        metadata.update(self._substrate_metadata(request, apex))
        error_message: str | None = (
            f"{type(framework_error).__name__}: {framework_error}"
            if framework_error is not None
            else None
        )

        result = CoordinationTopologyEvaluationResult(
            evaluation_id=evaluation_id,
            chain_id=self._chain_id,
            topology_id=self._topology.topology_id,
            topology_name=self._topology.name,
            topology_version=self._topology.version,
            runtime_instance_id=self._instance_id,
            sequence=sequence,
            coordination_id=request.coordination_id,
            coordination_message_id=request.coordination_message_id,
            sender_id=request.sender_id,
            recipient_id=request.recipient_id,
            recipient_kind=request.recipient_kind,
            aggregate_decision=apex,
            findings=tuple(findings),
            evaluator_names=tuple(evaluator_names),
            chain_depth=request.chain_depth,
            max_chain_depth=self._topology.max_chain_depth,
            reason=reason,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            matched_edge_id=matched_edge_id,
            matched_path_id=matched_path_id,
            correlation_id=request.correlation_id,
            parent_coordination_id=request.parent_coordination_id,
            parent_message_id=request.parent_message_id,
            request_id=request_id,
            tenant_id=resolution.tenant_id,
            error=error_message,
            metadata=metadata,
        )
        trace = self._trace_from_result(
            result,
            request,
            tenant_authority_source=resolution.source.value,
        )
        record = result_to_record(result=result, trace=trace)
        try:
            await self._persistence.record_evaluation(record)
        except CoordinationTopologyPersistenceError as exc:
            trace = self._replace_trace_error(
                trace, f"persistence: {exc}"
            )
            return CoordinationTopologyEnvelope(
                trace=trace, error=exc
            )
        except Exception as exc:  # noqa: BLE001 — substrate never re-raises
            trace = self._replace_trace_error(
                trace,
                f"persistence failed: {type(exc).__name__}: {exc}",
            )
            return CoordinationTopologyEnvelope(
                trace=trace, error=exc
            )

        return CoordinationTopologyEnvelope(
            trace=trace,
            result=result,
            error=framework_error,
        )

    # ─── Internals ───────────────────────────────────────────────────

    def _resolve_evaluators(
        self, whitelist: tuple[str, ...] | None
    ) -> tuple[BaseCoordinationTopologyEvaluator, ...]:
        if whitelist is None:
            return tuple(self._registry)
        if not whitelist:
            raise CoordinationTopologyConfigurationError(
                "evaluator_names whitelist is empty; pass None to run "
                "every registered evaluator"
            )
        resolved: list[BaseCoordinationTopologyEvaluator] = []
        seen: set[str] = set()
        for name in sorted(whitelist):
            if name in seen:
                continue
            if not self._registry.has(name):
                raise CoordinationTopologyConfigurationError(
                    f"unknown evaluator in whitelist: {name!r}"
                )
            resolved.append(self._registry.get(name))
            seen.add(name)
        return tuple(resolved)

    def _substrate_metadata(
        self,
        request: CoordinationTopologyEvaluationRequest,
        apex: CoordinationTopologyDecision,
    ) -> dict[str, object]:
        return {
            CoordinationTopologyMetadataKey.TOPOLOGY_ID.value: str(
                self._topology.topology_id
            ),
            CoordinationTopologyMetadataKey.TOPOLOGY_NAME.value: self._topology.name,
            CoordinationTopologyMetadataKey.TOPOLOGY_VERSION.value: self._topology.version,
            CoordinationTopologyMetadataKey.CHAIN_ID.value: str(
                self._chain_id
            ),
            CoordinationTopologyMetadataKey.AGGREGATE_DECISION.value: apex.value,
            CoordinationTopologyMetadataKey.CHAIN_DEPTH.value: request.chain_depth,
            CoordinationTopologyMetadataKey.MAX_CHAIN_DEPTH.value: self._topology.max_chain_depth,
            "coordination.direction": request.direction.value,
            "coordination.message_type": request.message_type.value,
            "coordination.priority": int(request.priority),
        }

    def _trace_from_result(
        self,
        result: CoordinationTopologyEvaluationResult,
        request: CoordinationTopologyEvaluationRequest,
        *,
        tenant_authority_source: str | None = None,
    ) -> CoordinationTopologyTrace:
        return CoordinationTopologyTrace(
            evaluation_id=result.evaluation_id,
            chain_id=result.chain_id,
            topology_id=result.topology_id,
            topology_name=result.topology_name,
            topology_version=result.topology_version,
            runtime_instance_id=result.runtime_instance_id,
            sequence=result.sequence,
            coordination_id=result.coordination_id,
            coordination_message_id=result.coordination_message_id,
            sender_id=result.sender_id,
            recipient_id=result.recipient_id,
            recipient_kind=result.recipient_kind,
            direction=request.direction,
            message_type=request.message_type,
            priority=request.priority,
            aggregate_decision=result.aggregate_decision,
            evaluator_names=result.evaluator_names,
            finding_count=len(result.findings),
            chain_depth=result.chain_depth,
            max_chain_depth=result.max_chain_depth,
            matched_edge_id=result.matched_edge_id,
            matched_path_id=result.matched_path_id,
            correlation_id=result.correlation_id,
            parent_coordination_id=result.parent_coordination_id,
            parent_message_id=result.parent_message_id,
            request_id=result.request_id,
            tenant_id=result.tenant_id,
            started_at=result.started_at,
            ended_at=result.ended_at,
            latency_ms=result.latency_ms,
            error=result.error,
            metadata=dict(result.metadata),
            tenant_authority_source=tenant_authority_source,
        )

    def _replace_trace_error(
        self,
        trace: CoordinationTopologyTrace,
        error: str,
    ) -> CoordinationTopologyTrace:
        return CoordinationTopologyTrace(
            evaluation_id=trace.evaluation_id,
            chain_id=trace.chain_id,
            topology_id=trace.topology_id,
            topology_name=trace.topology_name,
            topology_version=trace.topology_version,
            runtime_instance_id=trace.runtime_instance_id,
            sequence=trace.sequence,
            coordination_id=trace.coordination_id,
            coordination_message_id=trace.coordination_message_id,
            sender_id=trace.sender_id,
            recipient_id=trace.recipient_id,
            recipient_kind=trace.recipient_kind,
            direction=trace.direction,
            message_type=trace.message_type,
            priority=trace.priority,
            aggregate_decision=trace.aggregate_decision,
            evaluator_names=trace.evaluator_names,
            finding_count=trace.finding_count,
            chain_depth=trace.chain_depth,
            max_chain_depth=trace.max_chain_depth,
            matched_edge_id=trace.matched_edge_id,
            matched_path_id=trace.matched_path_id,
            correlation_id=trace.correlation_id,
            parent_coordination_id=trace.parent_coordination_id,
            parent_message_id=trace.parent_message_id,
            request_id=trace.request_id,
            tenant_id=trace.tenant_id,
            started_at=trace.started_at,
            ended_at=trace.ended_at,
            latency_ms=trace.latency_ms,
            error=error,
            metadata=dict(trace.metadata),
            tenant_authority_source=trace.tenant_authority_source,
        )

    def _fail_fast(
        self,
        *,
        evaluation_id: CoordinationTopologyEvaluationId,
        request: CoordinationTopologyEvaluationRequest,
        resolution: AuthorityResolution,
        request_id: str | None,
        started_at: datetime,
        loop_start: float,
        error: BaseException,
    ) -> CoordinationTopologyEnvelope:
        loop = asyncio.get_event_loop()
        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000.0, 3)
        trace = CoordinationTopologyTrace(
            evaluation_id=evaluation_id,
            chain_id=self._chain_id,
            topology_id=self._topology.topology_id,
            topology_name=self._topology.name,
            topology_version=self._topology.version,
            runtime_instance_id=self._instance_id,
            sequence=0,
            coordination_id=request.coordination_id,
            coordination_message_id=request.coordination_message_id,
            sender_id=request.sender_id,
            recipient_id=request.recipient_id,
            recipient_kind=request.recipient_kind,
            direction=request.direction,
            message_type=request.message_type,
            priority=request.priority,
            aggregate_decision=CoordinationTopologyDecision.DENIED,
            evaluator_names=(),
            finding_count=0,
            chain_depth=request.chain_depth,
            max_chain_depth=self._topology.max_chain_depth,
            matched_edge_id=None,
            matched_path_id=None,
            correlation_id=request.correlation_id,
            parent_coordination_id=request.parent_coordination_id,
            parent_message_id=request.parent_message_id,
            request_id=request_id,
            tenant_id=resolution.tenant_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            error=f"{type(error).__name__}: {error}",
            metadata=dict(request.metadata),
            tenant_authority_source=resolution.source.value,
        )
        return CoordinationTopologyEnvelope(trace=trace, error=error)


__all__ = ["CoordinationTopologyRuntime"]
