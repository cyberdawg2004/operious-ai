"""`CoordinationPolicyRuntime` — apex policy evaluator.

One public method (`evaluate`) drives one policy evaluation end-to-
end:

    CoordinationPolicyRuntime.evaluate(request)
        → resolve evaluator chain (sorted-name order)
        → for each evaluator: invoke under defensive try/except,
                              collect findings
        → aggregate findings → apex decision + restrictions + escalations
        → build result + trace
        → persist record
        → return envelope

The runtime is the **single** producer of
`CoordinationPolicyEnvelope`. It NEVER raises — every failure mode
lands on the envelope.

What the runtime DOES NOT do (Sprint L2 Rule 9):

* dispatch messages,
* reroute coordination,
* invoke governance,
* execute agents,
* invoke tools,
* retry execution,
* mutate registries.

The runtime composes with the `CoordinationRuntime` via injection
(Sprint L2 Phase 5) — the coordination runtime calls `evaluate()`
before invoking governance. The two substrates remain isolated;
this runtime never touches governance directly.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Mapping, Sequence

from app.identity import (
    AuthorityResolution,
    request_authority_resolution,
)
from app.coordination.policy.contracts.requests import (
    CoordinationPolicyEvaluationRequest,
)
from app.coordination.policy.contracts.results import (
    CoordinationPolicyEvaluationResult,
)
from app.coordination.policy.enums import CoordinationPolicyDecision
from app.coordination.policy.envelopes import (
    CoordinationPolicyEnvelope,
)
from app.coordination.policy.evaluators.base import (
    BaseCoordinationPolicyEvaluator,
)
from app.coordination.policy.exceptions import (
    CoordinationPolicyConfigurationError,
    CoordinationPolicyPersistenceError,
)
from app.coordination.policy.identity import (
    CoordinationPolicyChainId,
    CoordinationPolicyEvaluationId,
    derive_chain_id,
    generate_evaluation_id,
)
from app.coordination.policy.models.findings import (
    CoordinationPolicyFinding,
)
from app.coordination.policy.persistence.repository import (
    CoordinationPolicyPersistenceProtocol,
)
from app.coordination.policy.persistence.serializers import (
    result_to_record,
)
from app.coordination.policy.registry.registry import (
    CoordinationPolicyRegistry,
)
from app.coordination.policy.runtime.aggregator import (
    build_policy_decision,
)
from app.coordination.policy.taxonomy import (
    CoordinationPolicyMetadataKey,
)
from app.coordination.policy.tracing import CoordinationPolicyTrace
from app.observability.context import get_request_id


class CoordinationPolicyRuntime:
    """Apex coordination-policy evaluator. Produces one envelope per call."""

    def __init__(
        self,
        *,
        registry: CoordinationPolicyRegistry,
        persistence: CoordinationPolicyPersistenceProtocol,
        chain_id_override: CoordinationPolicyChainId | None = None,
    ) -> None:
        if len(registry) == 0:
            raise CoordinationPolicyConfigurationError(
                "CoordinationPolicyRuntime requires at least one "
                "registered evaluator"
            )
        self._registry = registry
        self._persistence = persistence
        # Chain id is derived from the sorted evaluator names so two
        # runtimes with the same composition share the same chain id.
        self._chain_id: CoordinationPolicyChainId = (
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
    def chain_id(self) -> CoordinationPolicyChainId:
        return self._chain_id

    def known_evaluators(self) -> tuple[str, ...]:
        return self._registry.names()

    # ─── Public API ───────────────────────────────────────────────────

    async def evaluate(
        self, request: CoordinationPolicyEvaluationRequest
    ) -> CoordinationPolicyEnvelope:
        """Run one policy evaluation end-to-end. Never raises."""
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
        except CoordinationPolicyConfigurationError as exc:
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
        findings: list[CoordinationPolicyFinding] = []
        evaluator_names: list[str] = []
        framework_error: BaseException | None = None
        for evaluator in evaluators:
            evaluator_names.append(evaluator.name)
            try:
                emitted = await evaluator.evaluate(request)
            except Exception as exc:  # noqa: BLE001 — substrate never re-raises
                framework_error = exc
                # Continue collecting findings from subsequent evaluators
                # but record the error to surface on the envelope. The
                # finding stream is still complete from the surviving
                # evaluators (Rule 6 — inspectability).
                continue
            findings.extend(emitted)

        # Aggregate.
        apex, restrictions, escalations, reason = build_policy_decision(
            findings
        )

        # Sequence + persistence under lock.
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

            result = CoordinationPolicyEvaluationResult(
                evaluation_id=evaluation_id,
                chain_id=self._chain_id,
                runtime_instance_id=self._instance_id,
                sequence=sequence,
                coordination_id=request.coordination_id,
                coordination_message_id=request.coordination_message_id,
                sender_id=request.sender_id,
                recipient_id=request.recipient_id,
                recipient_kind=request.recipient_kind,
                aggregate_decision=apex,
                findings=tuple(findings),
                restrictions=restrictions,
                escalations=escalations,
                evaluator_names=tuple(evaluator_names),
                reason=reason,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=latency_ms,
                correlation_id=request.correlation_id,
                parent_coordination_id=request.parent_coordination_id,
                parent_message_id=request.parent_message_id,
                request_id=request_id,
                tenant_id=resolution.tenant_id,
                error=error_message,
                metadata=metadata,
            )
            trace = self._trace_from_result(result, request)
            record = result_to_record(result)
            try:
                await self._persistence.record_evaluation(record)
            except CoordinationPolicyPersistenceError as exc:
                error_message = f"persistence: {exc}"
                trace = self._replace_trace_error(trace, error_message)
                # Persistence failed → envelope reports failure but
                # the in-memory result is still available for the caller
                # via the trace (lineage continuity).
                return CoordinationPolicyEnvelope(
                    trace=trace, error=exc
                )
            except Exception as exc:  # noqa: BLE001 — substrate never re-raises
                error_message = (
                    f"persistence failed: {type(exc).__name__}: {exc}"
                )
                trace = self._replace_trace_error(trace, error_message)
                return CoordinationPolicyEnvelope(
                    trace=trace, error=exc
                )

        # Successful evaluation (may carry a framework_error from a
        # failing evaluator; surfaced on result.error + trace.error).
        return CoordinationPolicyEnvelope(
            trace=trace,
            result=result,
            error=framework_error,
        )

    # ─── Internals ───────────────────────────────────────────────────

    def _resolve_evaluators(
        self, whitelist: tuple[str, ...] | None
    ) -> tuple[BaseCoordinationPolicyEvaluator, ...]:
        if whitelist is None:
            return tuple(self._registry)
        if not whitelist:
            raise CoordinationPolicyConfigurationError(
                "evaluator_names whitelist is empty; pass None to run "
                "every registered evaluator"
            )
        resolved: list[BaseCoordinationPolicyEvaluator] = []
        seen: set[str] = set()
        for name in sorted(whitelist):
            if name in seen:
                continue
            if not self._registry.has(name):
                raise CoordinationPolicyConfigurationError(
                    f"unknown evaluator in whitelist: {name!r}"
                )
            resolved.append(self._registry.get(name))
            seen.add(name)
        return tuple(resolved)

    def _substrate_metadata(
        self,
        request: CoordinationPolicyEvaluationRequest,
        apex: CoordinationPolicyDecision,
    ) -> Mapping[str, object]:
        return {
            CoordinationPolicyMetadataKey.CHAIN_ID.value: str(
                self._chain_id
            ),
            CoordinationPolicyMetadataKey.AGGREGATE_DECISION.value: apex.value,
            "coordination.direction": request.direction.value,
            "coordination.message_type": request.message_type.value,
            "coordination.priority": int(request.priority),
        }

    def _trace_from_result(
        self,
        result: CoordinationPolicyEvaluationResult,
        request: CoordinationPolicyEvaluationRequest,
    ) -> CoordinationPolicyTrace:
        return CoordinationPolicyTrace(
            evaluation_id=result.evaluation_id,
            chain_id=result.chain_id,
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
            restriction_count=len(result.restrictions),
            escalation_count=len(result.escalations),
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
        )

    def _replace_trace_error(
        self, trace: CoordinationPolicyTrace, error: str
    ) -> CoordinationPolicyTrace:
        return CoordinationPolicyTrace(
            evaluation_id=trace.evaluation_id,
            chain_id=trace.chain_id,
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
            restriction_count=trace.restriction_count,
            escalation_count=trace.escalation_count,
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
        )

    def _fail_fast(
        self,
        *,
        evaluation_id: CoordinationPolicyEvaluationId,
        request: CoordinationPolicyEvaluationRequest,
        resolution: AuthorityResolution,
        request_id: str | None,
        started_at: datetime,
        loop_start: float,
        error: BaseException,
    ) -> CoordinationPolicyEnvelope:
        loop = asyncio.get_event_loop()
        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000.0, 3)
        from app.coordination.policy.enums import CoordinationPolicyDecision

        trace = CoordinationPolicyTrace(
            evaluation_id=evaluation_id,
            chain_id=self._chain_id,
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
            aggregate_decision=CoordinationPolicyDecision.DENY,
            evaluator_names=(),
            finding_count=0,
            restriction_count=0,
            escalation_count=0,
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
        )
        # Silence: `Sequence` is referenced only by `_resolve_evaluators`'
        # signature consumers; nothing to suppress here.
        _ = Sequence
        return CoordinationPolicyEnvelope(trace=trace, error=error)


__all__ = ["CoordinationPolicyRuntime"]
