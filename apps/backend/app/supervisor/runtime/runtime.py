"""`SupervisorRuntime` — apex inspection orchestrator.

One public method (`inspect`) drives one supervisor inspection
end-to-end:

    SupervisorRuntime.inspect(request)
        → validate request (live xor replay)
        → build `InspectionView` once (pure)
        → select evaluator subset (sorted-name order)
        → run each evaluator under a defensive try/except
        → aggregate via `build_supervisor_decision`
        → build `SupervisorTrace`
        → return `ExecutionInspectionEnvelope`

The runtime is the **single** producer of `ExecutionInspectionEnvelope`.
It NEVER raises — every failure mode lands on the envelope.

Determinism:

* evaluator iteration is sorted by registered name,
* per-evaluator outputs preserve internal ordering,
* the aggregator is pure (`build_supervisor_decision`),
* `finding_id`s are derived from a stable UUID5 seed,
* callers may pin `inspection_id` and `decision_id` via the request
  for byte-identical replay outputs.

What the runtime DOES NOT do:

* call into `AgentRuntime` / `GovernanceRuntime` / tool invokers,
* mutate any input,
* spawn background tasks,
* schedule retries.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Mapping, Sequence

from app.core.capability_gate import gate_or_deny
from app.core.deterministic_identity import derive_runtime_id
from app.governance.capability import (
    GovernanceRuntime,
    OperationalAct,
)
from app.identity import AuthorityResolution, resolve_authority
from app.observability.context import get_request_id
from app.execution.persistence import ExecutionPersistenceProtocol
from app.governance.persistence import BaseGovernanceRepository
from app.session.persistence import SessionPersistenceProtocol
from app.supervisor.contracts.decisions import (
    SupervisorDecision,
    build_supervisor_decision,
)
from app.supervisor.contracts.evaluations import QAEvaluation
from app.supervisor.contracts.requests import ExecutionInspectionRequest
from app.supervisor.contracts.results import ExecutionInspectionResult
from app.supervisor.envelopes import ExecutionInspectionEnvelope
from app.supervisor.enums import (
    EvaluationStatus,
    InspectionMode,
    SupervisorDecisionKind,
)
from app.supervisor.evaluators.base import BaseEvaluator
from app.supervisor.evaluators.registry import EvaluatorRegistry
from app.supervisor.exceptions import (
    InspectionRequestError,
    SupervisorEvaluationError,
    SupervisorPersistenceError,
)
from app.supervisor.identity import (
    derive_session_decision_id,
    derive_session_inspection_id,
)
from app.supervisor.models.view import InspectionView
from app.supervisor.persistence import (
    BaseSupervisorRepository,
    InspectionRecord,
)
from app.supervisor.persistence.serializers import (
    InspectionRecordSet,
    inspection_envelope_to_records,
)
from app.supervisor.runtime.session_evidence import (
    load_session_inspection_evidence,
)
from app.supervisor.runtime.view_builder import (
    build_inspection_view_from_envelope,
    build_inspection_view_from_records,
)
from app.supervisor.tracing import EvaluatorTrace, SupervisorTrace

_RUNTIME_NAMESPACE = uuid.UUID("e4ed8a1a-13be-4ac1-bd19-1a2dbe50600c")
_INSPECTION_NAMESPACE = uuid.UUID("e4ed8a1a-13be-4ac1-bd19-1a2dbe50600d")
_DECISION_NAMESPACE = uuid.UUID("e4ed8a1a-13be-4ac1-bd19-1a2dbe50600e")


class SupervisorRuntime:
    """Apex supervisor orchestrator. Produces one envelope per call."""

    def __init__(
        self,
        *,
        evaluator_registry: EvaluatorRegistry,
        scoring_weights: Mapping[str, float] | None = None,
        governance: GovernanceRuntime | None = None,
        supervisor_repository: BaseSupervisorRepository | None = None,
        session_persistence: SessionPersistenceProtocol | None = None,
        execution_persistence: ExecutionPersistenceProtocol | None = None,
        governance_repository: BaseGovernanceRepository | None = None,
    ) -> None:
        self._registry = evaluator_registry
        self._scoring_weights: dict[str, float] = dict(scoring_weights or {})
        self._instance_id = derive_runtime_id(
            namespace=_RUNTIME_NAMESPACE,
            tenant_id=None,
            seed_components=(
                "supervisor_runtime",
                evaluator_registry.names(),
                self._scoring_weights,
            ),
        )
        # 2.75-\u03b1: capability legality gate. Inert when None.
        self._capability_governance = governance
        self._supervisor_repository = supervisor_repository
        self._session_persistence = session_persistence
        self._execution_persistence = execution_persistence
        self._governance_repository = governance_repository

    # ─── Inspection ───────────────────────────────────────────────────

    @property
    def runtime_instance_id(self) -> uuid.UUID:
        return self._instance_id

    def known_evaluators(self) -> tuple[str, ...]:
        return self._registry.names()

    # ─── Public API ───────────────────────────────────────────────────

    async def inspect(
        self,
        request: ExecutionInspectionRequest,
    ) -> ExecutionInspectionEnvelope:
        """Run one inspection end-to-end. Never raises."""
        loop = asyncio.get_event_loop()
        started_at = datetime.now(timezone.utc)
        loop_start = loop.time()
        inspection_id = request.inspection_id_override or derive_runtime_id(
            namespace=_INSPECTION_NAMESPACE,
            tenant_id=request.tenant_id,
            seed_components=(
                "supervisor_inspection",
                request.execution_id,
                request.correlation_id,
                request.request_id,
                request.metadata,
            ),
        )
        request_id = request.request_id or get_request_id()

        # Wedge B6: SINGULAR authority resolution.
        # Audit defect DR-3 was that this runtime coalesced
        # ``request.tenant_id`` with ``view.tenant_id`` in TWO places
        # (here + fail_fast) without recording which source won —
        # replay reconstruction could not audit the attribution chain.
        # The fix: call ``resolve_authority`` ONCE per inspection,
        # producing both the effective tenant_id AND the source
        # (typed_authority / legacy_tenant / observed_tenant / none).
        # Every downstream stamp (result, trace, view) consumes this
        # single resolution. The view_builder's internal coalescing
        # becomes a no-op when this runtime is the caller because we
        # pre-resolve and pass the resolved value down.
        observed_tenant_id = self._extract_observed_tenant_id(request)
        resolution = resolve_authority(
            typed=request.authority,
            legacy_tenant_id=request.tenant_id,
            observed_tenant_id=observed_tenant_id,
        )

        # 2.75-\u03b1: capability legality gate. Inert when None.
        denial = await gate_or_deny(
            self._capability_governance,
            act=OperationalAct.SUPERVISOR_INSPECT,
            authority=request.authority,
            resolution=resolution,
            actor="supervisor_runtime",
        )
        if denial is not None:
            return self._fail_fast_envelope(
                inspection_id=inspection_id,
                request=request,
                request_id=request_id,
                started_at=started_at,
                loop_start=loop_start,
                error=denial,
                inspection_mode=InspectionMode.LIVE
                if request.live_envelope is not None
                else InspectionMode.REPLAY,
                resolution=resolution,
            )

        # 1. Validate + build the view.
        try:
            view, mode = self._build_view(request, resolution=resolution)
        except InspectionRequestError as exc:
            return self._fail_fast_envelope(
                inspection_id=inspection_id,
                request=request,
                request_id=request_id,
                started_at=started_at,
                loop_start=loop_start,
                error=exc,
                inspection_mode=InspectionMode.LIVE
                if request.live_envelope is not None
                else InspectionMode.REPLAY,
                resolution=resolution,
            )

        # 2. Resolve evaluator subset (sorted-name order).
        try:
            evaluators = self._resolve_evaluators(request.evaluator_names)
        except InspectionRequestError as exc:
            return self._fail_fast_envelope(
                inspection_id=inspection_id,
                request=request,
                request_id=request_id,
                started_at=started_at,
                loop_start=loop_start,
                error=exc,
                inspection_mode=mode,
                resolution=resolution,
                view=view,
            )

        # 3. Run each evaluator under a defensive try/except.
        evaluations, evaluator_traces = await self._run_evaluators(
            evaluators=evaluators,
            view=view,
        )

        # 4. Aggregate.
        decision = build_supervisor_decision(
            evaluations=evaluations,
            scoring_weights=self._scoring_weights,
            decision_id=request.decision_id_override,
        )

        # 5. Build the result + trace + envelope.
        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000.0, 3)

        # Lineage discipline: the caller's pipeline owns its own
        # correlation. We carry it onto the result + trace verbatim
        # when supplied, and only fall back to the inspected
        # execution's own value when the caller did not pre-establish
        # any. Tenant attribution is handled by ``resolution`` above.
        effective_correlation_id = (
            request.correlation_id
            if request.correlation_id is not None
            else view.correlation_id
        )

        result = ExecutionInspectionResult(
            inspection_id=inspection_id,
            execution_id=view.execution_id,
            runtime_instance_id=self._instance_id,
            correlation_id=effective_correlation_id,
            request_id=request_id,
            tenant_id=resolution.tenant_id,
            tenant_authority_source=resolution.source.value,
            inspection_mode=mode,
            evaluations=tuple(evaluations),
            decision=decision,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            metadata=dict(request.metadata),
        )

        trace = SupervisorTrace(
            inspection_id=inspection_id,
            execution_id=view.execution_id,
            runtime_instance_id=self._instance_id,
            correlation_id=effective_correlation_id,
            request_id=request_id,
            tenant_id=resolution.tenant_id,
            tenant_authority_source=resolution.source.value,
            inspection_mode=mode,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            evaluator_traces=tuple(evaluator_traces),
            decision_kind=decision.kind,
            aggregate_score=decision.aggregate_score,
            finding_count=len(decision.findings),
            escalation_count=len(decision.escalations),
            metadata=dict(request.metadata),
        )

        return ExecutionInspectionEnvelope(trace=trace, result=result)

    async def evaluate_session(self, session_id: str) -> InspectionRecord:
        """Evaluate one closed session from persisted evidence only.

        Phase 3-A intentionally exposes a one-argument entrypoint. The
        runtime reconstructs the tenant, timeline, terminal execution,
        and governance evidence from persistence; callers never supply
        live runtime objects or reconstructed records.
        """

        repository = self._supervisor_repository
        session_persistence = self._session_persistence
        execution_persistence = self._execution_persistence
        if (
            repository is None
            or session_persistence is None
            or execution_persistence is None
        ):
            raise SupervisorEvaluationError(
                "evaluate_session requires supervisor, session, and "
                "execution persistence dependencies"
            )

        evidence = await load_session_inspection_evidence(
            session_id=session_id,
            session_persistence=session_persistence,
            execution_persistence=execution_persistence,
            governance_repository=self._governance_repository,
        )
        inspection_id = derive_session_inspection_id(
            session_id=evidence.session.session_id,
            execution_id=evidence.execution.execution_id,
            tenant_id=evidence.tenant_id,
        )
        existing = await repository.get_inspection(
            str(inspection_id),
            expected_tenant_id=evidence.tenant_id,
        )
        if existing is not None:
            return existing

        envelope = await self.inspect(
            ExecutionInspectionRequest(
                execution_id=uuid.UUID(str(evidence.execution.execution_id)),
                tenant_id=evidence.tenant_id,
                recorded_execution=evidence.recorded_execution,
                recorded_tool_invocations=evidence.recorded_tool_invocations,
                recorded_governance_decisions=evidence.governance_decisions,
                inspection_id_override=inspection_id,
                decision_id_override=derive_session_decision_id(
                    inspection_id=inspection_id
                ),
                metadata=evidence.metadata(),
            )
        )
        record_set = inspection_envelope_to_records(envelope)
        if record_set is None:
            raise SupervisorEvaluationError(
                "persisted session supervisor evaluation failed"
            ) from envelope.error
        try:
            await self._record_inspection_set(record_set)
        except SupervisorPersistenceError:
            existing = await repository.get_inspection(
                str(inspection_id),
                expected_tenant_id=evidence.tenant_id,
            )
            if existing is not None:
                return existing
            raise
        return record_set.inspection

    # ─── Internals ────────────────────────────────────────────────────

    async def _record_inspection_set(
        self, record_set: InspectionRecordSet
    ) -> None:
        repository = self._supervisor_repository
        if repository is None:
            raise SupervisorEvaluationError(
                "evaluate_session requires supervisor persistence"
            )
        await repository.record_inspection(record_set.inspection)
        for finding in record_set.findings:
            await repository.record_finding(finding)
        for evaluation in record_set.evaluations:
            await repository.record_evaluation(evaluation)
        for escalation in record_set.escalations:
            await repository.record_escalation(escalation)

    @staticmethod
    def _extract_observed_tenant_id(
        request: ExecutionInspectionRequest,
    ) -> str | None:
        """Read the underlying execution's observed tenant_id.

        Wedge B6 separates "observed tenant" (what the inspected
        execution itself carries) from the resolved authority.
        ``resolve_authority`` consumes the observed value as the
        lowest-priority fallback. Returns ``None`` when neither
        inspection source is present — the request will then fail
        validation in ``_build_view`` and the fail-fast path uses
        the same ``None`` observation.
        """
        if request.live_envelope is not None:
            return request.live_envelope.trace.tenant_id
        if request.recorded_execution is not None:
            return request.recorded_execution.tenant_id
        return None

    def _build_view(
        self,
        request: ExecutionInspectionRequest,
        *,
        resolution: AuthorityResolution,
    ) -> tuple[InspectionView, InspectionMode]:
        has_live = request.live_envelope is not None
        has_replay = request.recorded_execution is not None

        if has_live and has_replay:
            raise InspectionRequestError(
                "ExecutionInspectionRequest cannot carry BOTH a live "
                "envelope and replay records; choose one source."
            )
        if not has_live and not has_replay:
            raise InspectionRequestError(
                "ExecutionInspectionRequest must carry either a live "
                "envelope or a `recorded_execution`."
            )

        # Wedge B6: pass the resolved tenant_id (NOT request.tenant_id)
        # down to the view builder. This makes the runtime's authority
        # resolution singular — the view_builder no longer participates
        # in coalescing in the runtime path. Its ``tenant_id`` override
        # parameter still exists for external callers (tests, future
        # replay tooling) but the runtime never relies on
        # view_builder's internal fallback.
        if has_live:
            envelope = request.live_envelope
            assert envelope is not None
            if envelope.trace.execution_id != request.execution_id:
                raise InspectionRequestError(
                    "live_envelope.trace.execution_id does not match "
                    "request.execution_id"
                )
            view = build_inspection_view_from_envelope(
                envelope, tenant_id=resolution.tenant_id
            )
            return view, InspectionMode.LIVE

        execution = request.recorded_execution
        assert execution is not None
        if uuid.UUID(execution.execution_id) != request.execution_id:
            raise InspectionRequestError(
                "recorded_execution.execution_id does not match "
                "request.execution_id"
            )
        view = build_inspection_view_from_records(
            execution=execution,
            tool_invocations=request.recorded_tool_invocations,
            governance_decisions=request.recorded_governance_decisions,
            tenant_id=resolution.tenant_id,
        )
        return view, InspectionMode.REPLAY

    def _resolve_evaluators(
        self, whitelist: tuple[str, ...] | None
    ) -> tuple[BaseEvaluator, ...]:
        if whitelist is None:
            return tuple(self._registry)  # sorted-name order
        if not whitelist:
            raise InspectionRequestError(
                "evaluator_names whitelist is empty; pass None to run "
                "every registered evaluator"
            )
        # Deterministic sorted order over the intersection.
        resolved: list[BaseEvaluator] = []
        seen: set[str] = set()
        for name in sorted(whitelist):
            if name in seen:
                continue
            if not self._registry.has(name):
                raise InspectionRequestError(
                    f"unknown evaluator in whitelist: {name!r}"
                )
            resolved.append(self._registry.get(name))
            seen.add(name)
        return tuple(resolved)

    async def _run_evaluators(
        self,
        *,
        evaluators: Sequence[BaseEvaluator],
        view: InspectionView,
    ) -> tuple[list[QAEvaluation], list[EvaluatorTrace]]:
        loop = asyncio.get_event_loop()
        evaluations: list[QAEvaluation] = []
        traces: list[EvaluatorTrace] = []
        for evaluator in evaluators:
            ev_started = datetime.now(timezone.utc)
            ev_loop_start = loop.time()
            try:
                evaluation = await evaluator.evaluate(view)
            except Exception as exc:
                ev_ended = datetime.now(timezone.utc)
                ev_latency = round((loop.time() - ev_loop_start) * 1000.0, 3)
                evaluations.append(
                    QAEvaluation(
                        evaluator_name=evaluator.name,
                        status=EvaluationStatus.ERRORED,
                        score=0.0,
                        findings=(),
                        started_at=ev_started,
                        ended_at=ev_ended,
                        latency_ms=ev_latency,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                traces.append(
                    EvaluatorTrace(
                        evaluator_name=evaluator.name,
                        status=EvaluationStatus.ERRORED,
                        started_at=ev_started,
                        ended_at=ev_ended,
                        latency_ms=ev_latency,
                        finding_count=0,
                        score=0.0,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue

            ev_ended = datetime.now(timezone.utc)
            ev_latency = round((loop.time() - ev_loop_start) * 1000.0, 3)
            evaluations.append(evaluation)
            traces.append(
                EvaluatorTrace(
                    evaluator_name=evaluator.name,
                    status=evaluation.status,
                    started_at=evaluation.started_at,
                    ended_at=evaluation.ended_at,
                    latency_ms=evaluation.latency_ms,
                    finding_count=len(evaluation.findings),
                    score=evaluation.score,
                    error=evaluation.error,
                )
            )
            # Suppress unused-variable lint; kept for symmetry / future use.
            _ = ev_latency

        return evaluations, traces

    def _fail_fast_envelope(
        self,
        *,
        inspection_id: uuid.UUID,
        request: ExecutionInspectionRequest,
        request_id: str | None,
        started_at: datetime,
        loop_start: float,
        error: BaseException,
        inspection_mode: InspectionMode,
        resolution: AuthorityResolution,
        view: InspectionView | None = None,
    ) -> ExecutionInspectionEnvelope:
        loop = asyncio.get_event_loop()
        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000.0, 3)

        # Synthesize a no-result `SupervisorDecision` for the trace so
        # downstream consumers see a well-shaped envelope even on
        # request-validation failure.
        synthetic_decision = SupervisorDecision(
            decision_id=request.decision_id_override
            or derive_runtime_id(
                namespace=_DECISION_NAMESPACE,
                tenant_id=resolution.tenant_id,
                seed_components=(
                    "supervisor_fail_fast_decision",
                    inspection_id,
                    request.execution_id,
                    type(error).__name__,
                    str(error),
                    request.metadata,
                ),
            ),
            kind=SupervisorDecisionKind.REJECT,
            aggregate_score=0.0,
            findings=(),
            escalations=(),
            reason=f"inspection failed: {type(error).__name__}: {error}",
            decided_at=ended_at,
        )
        _ = synthetic_decision  # not surfaced on the envelope (no result)

        # Wedge B6: the fail-fast path consumes the SAME resolution
        # produced once at the top of ``inspect()``. The audit-flagged
        # second coalescing site (``request.tenant_id if view is None
        # else view.tenant_id``) is closed — fail-fast no longer
        # diverges from the normal path on authority attribution.
        trace = SupervisorTrace(
            inspection_id=inspection_id,
            execution_id=request.execution_id,
            runtime_instance_id=self._instance_id,
            correlation_id=request.correlation_id
            if view is None
            else view.correlation_id,
            request_id=request_id,
            tenant_id=resolution.tenant_id,
            tenant_authority_source=resolution.source.value,
            inspection_mode=inspection_mode,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            evaluator_traces=(),
            decision_kind=SupervisorDecisionKind.REJECT,
            aggregate_score=0.0,
            finding_count=0,
            escalation_count=0,
            error=f"{type(error).__name__}: {error}",
            metadata=dict(request.metadata),
        )
        return ExecutionInspectionEnvelope(trace=trace, error=error)


__all__ = ["SupervisorRuntime"]
