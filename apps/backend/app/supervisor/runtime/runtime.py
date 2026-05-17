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

from app.observability.context import get_request_id
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
from app.supervisor.exceptions import InspectionRequestError
from app.supervisor.models.view import InspectionView
from app.supervisor.runtime.view_builder import (
    build_inspection_view_from_envelope,
    build_inspection_view_from_records,
)
from app.supervisor.tracing import EvaluatorTrace, SupervisorTrace


class SupervisorRuntime:
    """Apex supervisor orchestrator. Produces one envelope per call."""

    def __init__(
        self,
        *,
        evaluator_registry: EvaluatorRegistry,
        scoring_weights: Mapping[str, float] | None = None,
    ) -> None:
        self._registry = evaluator_registry
        self._scoring_weights: dict[str, float] = dict(scoring_weights or {})
        self._instance_id = uuid.uuid4()

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
        inspection_id = request.inspection_id_override or uuid.uuid4()
        request_id = request.request_id or get_request_id()

        # 1. Validate + build the view.
        try:
            view, mode = self._build_view(request)
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
        # correlation / tenant. We carry those onto the result + trace
        # verbatim when supplied, and only fall back to the inspected
        # execution's own values when the caller did not pre-establish
        # any. This matches the `ExecutionInspectionRequest` docstring
        # contract ("carried through onto the inspection result + trace")
        # and lets supervisor inspections rejoin the orchestrator's
        # pipeline trace.
        effective_correlation_id = (
            request.correlation_id
            if request.correlation_id is not None
            else view.correlation_id
        )
        effective_tenant_id = (
            request.tenant_id
            if request.tenant_id is not None
            else view.tenant_id
        )

        result = ExecutionInspectionResult(
            inspection_id=inspection_id,
            execution_id=view.execution_id,
            runtime_instance_id=self._instance_id,
            correlation_id=effective_correlation_id,
            request_id=request_id,
            tenant_id=effective_tenant_id,
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
            tenant_id=effective_tenant_id,
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

    # ─── Internals ────────────────────────────────────────────────────

    def _build_view(
        self, request: ExecutionInspectionRequest
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

        if has_live:
            envelope = request.live_envelope
            assert envelope is not None
            if envelope.trace.execution_id != request.execution_id:
                raise InspectionRequestError(
                    "live_envelope.trace.execution_id does not match "
                    "request.execution_id"
                )
            view = build_inspection_view_from_envelope(
                envelope, tenant_id=request.tenant_id
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
            tenant_id=request.tenant_id,
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
        view: InspectionView | None = None,
    ) -> ExecutionInspectionEnvelope:
        loop = asyncio.get_event_loop()
        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000.0, 3)

        # Synthesize a no-result `SupervisorDecision` for the trace so
        # downstream consumers see a well-shaped envelope even on
        # request-validation failure.
        synthetic_decision = SupervisorDecision(
            decision_id=request.decision_id_override or uuid.uuid4(),
            kind=SupervisorDecisionKind.REJECT,
            aggregate_score=0.0,
            findings=(),
            escalations=(),
            reason=f"inspection failed: {type(error).__name__}: {error}",
            decided_at=ended_at,
        )
        _ = synthetic_decision  # not surfaced on the envelope (no result)

        trace = SupervisorTrace(
            inspection_id=inspection_id,
            execution_id=request.execution_id,
            runtime_instance_id=self._instance_id,
            correlation_id=request.correlation_id
            if view is None
            else view.correlation_id,
            request_id=request_id,
            tenant_id=request.tenant_id
            if view is None
            else view.tenant_id,
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
