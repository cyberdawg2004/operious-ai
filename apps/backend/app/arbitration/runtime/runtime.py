"""`OperationalArbitrationRuntime` — apex inspect-only evaluator.

Sprint L4 critical guarantees:

* Arbitration is **interpretive authority**, NOT execution authority.
* The runtime NEVER executes, dispatches, retries, or invokes any
  tool / agent / sibling runtime.
* The runtime NEVER raises from `evaluate()`. Failures (evaluator
  raised, persistence failed) are folded onto the envelope as
  `ARBITRATION_ERROR`.
* Evaluator ordering is deterministic — sorted by evaluator name,
  applied via the registry.
* All outputs are immutable, replay-safe value objects.

This runtime is a **sibling** of governance / topology / policy /
coordination — it is NOT inlined into any dispatch path. Callers
(audit / supervisor surfaces, replay harnesses) submit
arbitration cases explicitly via `evaluate()`.
"""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone

from app.core.deterministic_identity import derive_runtime_id
from app.arbitration.contracts.requests import ArbitrationRequest
from app.arbitration.contracts.results import ArbitrationResult
from app.arbitration.envelopes import ArbitrationEnvelope
from app.arbitration.enums import (
    ArbitrationAuthorityLevel,
    ArbitrationOutcome,
)
from app.arbitration.evaluators.base import (
    ArbitrationEvaluatorOutput,
    BaseArbitrationEvaluator,
)
from app.arbitration.exceptions import (
    ArbitrationConfigurationError,
    ArbitrationEvaluationError,
    ArbitrationPersistenceError,
    DuplicateArbitrationRecordError,
)
from app.arbitration.identity import (
    ArbitrationChainId,
    ArbitrationEvaluationId,
    derive_chain_id,
    derive_finding_id,
    generate_evaluation_id,
)
from app.arbitration.models.conflict import ArbitrationConflict
from app.arbitration.models.deadlock import DeadlockWitness
from app.arbitration.models.decision import ArbitrationDecision
from app.arbitration.models.findings import ArbitrationFinding
from app.identity import (
    AuthorityResolution,
    request_authority_resolution,
)
from app.arbitration.persistence.repository import (
    ArbitrationPersistenceProtocol,
)
from app.arbitration.persistence.serializers import (
    result_to_record,
)
from app.arbitration.registry.registry import (
    ArbitrationEvaluatorRegistry,
)
from app.arbitration.runtime.aggregator import (
    build_arbitration_decision,
)
from app.arbitration.taxonomy import (
    ArbitrationFindingCode,
    ArbitrationMetadataKey,
)
from app.arbitration.tracing import ArbitrationTrace
from app.governance.capability import (
    GovernanceRuntime,
    OperationalAct,
    evaluate_capability_gate,
)

_logger = logging.getLogger(__name__)
_RUNTIME_NAMESPACE = uuid.UUID("e4ed8a1a-13be-4ac1-bd19-1a2dbe50600b")


class OperationalArbitrationRuntime:
    """Apex inspect-only arbitration evaluator.

    Composition (registry of evaluators + optional persistence) is
    fixed at construction time. The runtime exposes ONE public
    method, `evaluate`, which is read-only over its dependencies.
    """

    __slots__ = (
        "_registry",
        "_persistence",
        "_runtime_instance_id",
        "_sequence",
        "_sequence_lock",
        "_capability_governance",
    )

    def __init__(
        self,
        *,
        registry: ArbitrationEvaluatorRegistry,
        persistence: ArbitrationPersistenceProtocol | None = None,
        governance: GovernanceRuntime | None = None,
    ) -> None:
        if len(registry) == 0:
            raise ArbitrationConfigurationError(
                "OperationalArbitrationRuntime requires a non-empty "
                "ArbitrationEvaluatorRegistry."
            )
        self._registry = registry
        self._persistence = persistence
        self._runtime_instance_id = derive_runtime_id(
            namespace=_RUNTIME_NAMESPACE,
            tenant_id=None,
            seed_components=(
                "operational_arbitration_runtime",
                registry.names(),
            ),
        )
        self._sequence: int = 0
        # 2.75-\u03b1: capability legality gate. Inert when
        # ``governance is None``. Production composition root pins
        # a configured runtime so every ``evaluate`` is gated
        # against ``OperationalAct.ARBITRATION_EVALUATE``.
        self._capability_governance = governance
        # Chronology Integrity (Core Law 3) — sequence assignment must
        # be atomic across concurrent ``evaluate()`` invocations. The
        # lock is held ONLY for the increment; persistence and trace
        # construction happen outside the lock so we do not throttle
        # the runtime on disk I/O (matches the lock-split doctrine
        # adopted by coordination/policy/topology in 2.5-D).
        self._sequence_lock: asyncio.Lock = asyncio.Lock()

    async def _next_sequence(self) -> int:
        async with self._sequence_lock:
            self._sequence += 1
            return self._sequence

    @property
    def runtime_instance_id(self) -> uuid.UUID:
        return self._runtime_instance_id

    @property
    def registry(self) -> ArbitrationEvaluatorRegistry:
        return self._registry

    @property
    def persistence(
        self,
    ) -> ArbitrationPersistenceProtocol | None:
        return self._persistence

    async def evaluate(
        self, request: ArbitrationRequest
    ) -> ArbitrationEnvelope:
        """Inspect a case and produce one immutable arbitration envelope.

        Never raises. All failures are folded onto the envelope.
        """
        started_at = datetime.now(tz=timezone.utc)
        t0 = time.perf_counter()
        # P2-A: singular authority resolution at the runtime entry. The
        # resolved ``tenant_id`` replaces every ``request.tenant_id`` read
        # below so the typed-ingress surface (Branch A) is honored
        # uniformly without per-site coalescing.
        resolution = request_authority_resolution(request)
        evaluation_id = (
            request.evaluation_id_override
            if request.evaluation_id_override is not None
            else generate_evaluation_id()
        )

        # 2.75-\u03b1: capability legality gate. Inert when
        # ``self._capability_governance`` is unconfigured.
        # 2.75-\u03b4: capture governance provenance (decision_id,
        # chain_id) from the gate outcome so the apex
        # ``ArbitrationTrace`` records who authorised this evaluate
        # call. Joinable by id against the governance repository.
        gate_outcome = await evaluate_capability_gate(
            self._capability_governance,
            act=OperationalAct.ARBITRATION_EVALUATE,
            authority=request.authority,
            resolution=resolution,
            actor="arbitration_runtime",
        )
        if gate_outcome.denial is not None:
            return await self._failed_envelope(
                request=request,
                resolution=resolution,
                evaluation_id=evaluation_id,
                evaluators=(),
                started_at=started_at,
                t0=t0,
                error=gate_outcome.denial,
                error_outcome=ArbitrationOutcome.ARBITRATION_ERROR,
                reason=str(gate_outcome.denial),
                governance_decision_id=gate_outcome.decision_id,
                governance_chain_id=gate_outcome.chain_id,
            )

        # Resolve evaluators (registry sorted by name).
        try:
            evaluators = self._resolve_evaluators(request)
        except ArbitrationConfigurationError as exc:
            return await self._failed_envelope(
                request=request,
                resolution=resolution,
                evaluation_id=evaluation_id,
                evaluators=(),
                started_at=started_at,
                t0=t0,
                error=exc,
                error_outcome=ArbitrationOutcome.ARBITRATION_ERROR,
                reason=f"evaluator resolution failed: {exc}",
            )

        evaluator_names = tuple(e.name for e in evaluators)
        chain_id = derive_chain_id(evaluator_names=evaluator_names)

        all_findings: list[ArbitrationFinding] = []
        all_conflicts: list[ArbitrationConflict] = []
        all_witnesses: list[DeadlockWitness] = []
        framework_error: BaseException | None = None

        for evaluator in evaluators:
            try:
                output = evaluator.evaluate(
                    request, evaluation_id=evaluation_id
                )
            except Exception as exc:  # noqa: BLE001
                _logger.exception(
                    "arbitration evaluator %s raised; folding onto "
                    "envelope as RESOLUTION_INCONCLUSIVE",
                    evaluator.name,
                )
                framework_error = ArbitrationEvaluationError(
                    f"evaluator {evaluator.name!r} raised: "
                    f"{exc.__class__.__name__}: {exc}"
                )
                framework_error.__cause__ = exc
                all_findings.append(
                    self._evaluator_failure_finding(
                        evaluator_name=evaluator.name,
                        evaluation_id=evaluation_id,
                        ordinal=len(all_findings),
                        error=exc,
                    )
                )
                continue

            output = self._coerce_output(output, evaluator.name)
            all_findings.extend(output.findings)
            all_conflicts.extend(output.conflicts)
            all_witnesses.extend(output.deadlock_witnesses)

        decision = (
            build_arbitration_decision(
                signals=request.case.signals,
                conflicts=all_conflicts,
                deadlock_witnesses=all_witnesses,
            )
            if framework_error is None
            else ArbitrationDecision(
                outcome=ArbitrationOutcome.ARBITRATION_ERROR,
                prevailing_authority=None,
                reason=str(framework_error),
            )
        )

        # Apex finding: authority precedence applied (resolutions only).
        if (
            framework_error is None
            and decision.outcome
            in {
                ArbitrationOutcome.ARBITRATION_RESOLVED,
                ArbitrationOutcome.ARBITRATION_ESCALATED,
            }
            and decision.prevailing_authority is not None
        ):
            all_findings.append(
                self._authority_precedence_finding(
                    evaluation_id=evaluation_id,
                    ordinal=len(all_findings),
                    decision=decision,
                )
            )

        ended_at = datetime.now(tz=timezone.utc)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        sequence = await self._next_sequence()
        runtime_instance_id = self._runtime_instance_id_for_request(request)

        result = ArbitrationResult(
            evaluation_id=evaluation_id,
            chain_id=chain_id,
            case_id=request.case.case_id,
            runtime_instance_id=runtime_instance_id,
            sequence=sequence,
            decision=decision,
            findings=tuple(all_findings),
            conflicts=tuple(all_conflicts),
            deadlock_witnesses=tuple(all_witnesses),
            evaluator_names=evaluator_names,
            signal_count=request.case.signal_count,
            recommendation_count=request.case.recommendation_count,
            iteration_count=request.case.iteration_count,
            max_iterations=request.case.max_iterations,
            reason=decision.reason,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            tenant_id=resolution.tenant_id,
            error=(
                str(framework_error)
                if framework_error is not None
                else None
            ),
            metadata=self._build_metadata(
                request=request,
                evaluation_id=evaluation_id,
                chain_id=chain_id,
                decision=decision,
                evaluator_names=evaluator_names,
                findings_count=len(all_findings),
                conflicts_count=len(all_conflicts),
                witnesses_count=len(all_witnesses),
            ),
        )

        trace = ArbitrationTrace(
            evaluation_id=evaluation_id,
            chain_id=chain_id,
            case_id=request.case.case_id,
            runtime_instance_id=runtime_instance_id,
            sequence=sequence,
            outcome=decision.outcome,
            evaluator_names=evaluator_names,
            finding_count=len(all_findings),
            conflict_count=len(all_conflicts),
            deadlock_witness_count=len(all_witnesses),
            signal_count=request.case.signal_count,
            recommendation_count=request.case.recommendation_count,
            iteration_count=request.case.iteration_count,
            max_iterations=request.case.max_iterations,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            tenant_id=resolution.tenant_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            error=(
                str(framework_error)
                if framework_error is not None
                else None
            ),
            metadata=result.metadata,
            tenant_authority_source=resolution.source.value,
            governance_decision_id=gate_outcome.decision_id,
            governance_chain_id=gate_outcome.chain_id,
        )

        # Persistence (best-effort; failure is folded onto envelope).
        if self._persistence is not None:
            try:
                await self._persistence.save(result_to_record(result))
            except DuplicateArbitrationRecordError as persistence_exc:
                if request.evaluation_id_override is not None:
                    _logger.info(
                        "arbitration persistence replay reused "
                        "evaluation_id=%s",
                        evaluation_id,
                    )
                    return ArbitrationEnvelope(
                        trace=trace,
                        result=result,
                        error=framework_error,
                    )
                _logger.exception(
                    "arbitration persistence failed for "
                    "evaluation_id=%s",
                    evaluation_id,
                )
                return ArbitrationEnvelope(
                    trace=trace,
                    result=result,
                    error=persistence_exc,
                )
            except (
                ArbitrationPersistenceError,
                Exception,
            ) as persistence_exc:  # noqa: BLE001
                _logger.exception(
                    "arbitration persistence failed for "
                    "evaluation_id=%s",
                    evaluation_id,
                )
                # Return the result-bearing envelope but attach the
                # persistence error so callers can detect it without
                # losing the interpretive output.
                return ArbitrationEnvelope(
                    trace=trace,
                    result=result,
                    error=persistence_exc,
                )

        return ArbitrationEnvelope(
            trace=trace, result=result, error=framework_error
        )

    # ─── helpers ─────────────────────────────────────────────────────

    def _resolve_evaluators(
        self, request: ArbitrationRequest
    ) -> tuple[BaseArbitrationEvaluator, ...]:
        if request.evaluator_names is None:
            return tuple(self._registry)
        names = tuple(request.evaluator_names)
        if not names:
            raise ArbitrationConfigurationError(
                "request.evaluator_names was empty; pass None to use "
                "the full registered chain."
            )
        for name in names:
            if not self._registry.has(name):
                raise ArbitrationConfigurationError(
                    f"unknown arbitration evaluator: {name!r}"
                )
        return tuple(self._registry.get(name) for name in sorted(names))

    @staticmethod
    def _coerce_output(
        output: ArbitrationEvaluatorOutput | None,
        evaluator_name: str,
    ) -> ArbitrationEvaluatorOutput:
        # `evaluator_name` is preserved on the signature so the caller's
        # error reporting can stay symmetric across all coercion sites
        # — the contract may grow back a runtime check later (e.g. when
        # evaluators are registered via plugin entry points and their
        # outputs are dynamically typed).
        del evaluator_name
        if output is None:
            return ArbitrationEvaluatorOutput(findings=())
        return output

    @staticmethod
    def _evaluator_failure_finding(
        *,
        evaluator_name: str,
        evaluation_id: ArbitrationEvaluationId,
        ordinal: int,
        error: BaseException,
    ) -> ArbitrationFinding:
        return ArbitrationFinding(
            finding_id=derive_finding_id(
                evaluation_id=evaluation_id,
                evaluator_name=evaluator_name,
                code=ArbitrationFindingCode.RESOLUTION_INCONCLUSIVE.value,
                ordinal=ordinal,
            ),
            evaluator_name=evaluator_name,
            outcome_hint=ArbitrationOutcome.ARBITRATION_ERROR,
            code=ArbitrationFindingCode.RESOLUTION_INCONCLUSIVE.value,
            message=(
                f"evaluator {evaluator_name!r} raised "
                f"{error.__class__.__name__}: {error}"
            ),
            detected_at=datetime.now(tz=timezone.utc),
            metadata={
                "traceback": traceback.format_exception_only(
                    type(error), error
                )[-1].strip(),
            },
        )

    @staticmethod
    def _authority_precedence_finding(
        *,
        evaluation_id: ArbitrationEvaluationId,
        ordinal: int,
        decision: ArbitrationDecision,
    ) -> ArbitrationFinding:
        prevailing = decision.prevailing_authority
        assert prevailing is not None  # narrow for type-checkers
        return ArbitrationFinding(
            finding_id=derive_finding_id(
                evaluation_id=evaluation_id,
                evaluator_name="arbitration_runtime",
                code=ArbitrationFindingCode.AUTHORITY_PRECEDENCE_APPLIED.value,
                ordinal=ordinal,
            ),
            evaluator_name="arbitration_runtime",
            outcome_hint=decision.outcome,
            code=ArbitrationFindingCode.AUTHORITY_PRECEDENCE_APPLIED.value,
            message=decision.reason,
            authority=prevailing.level,
            detected_at=datetime.now(tz=timezone.utc),
        )

    @staticmethod
    def _build_metadata(
        *,
        request: ArbitrationRequest,
        evaluation_id: ArbitrationEvaluationId,
        chain_id: ArbitrationChainId,
        decision: ArbitrationDecision,
        evaluator_names: tuple[str, ...],
        findings_count: int,
        conflicts_count: int,
        witnesses_count: int,
    ) -> dict[str, object]:
        meta: dict[str, object] = dict(request.metadata)
        meta[ArbitrationMetadataKey.CASE_ID.value] = str(
            request.case.case_id
        )
        meta[ArbitrationMetadataKey.EVALUATION_ID.value] = str(
            evaluation_id
        )
        meta[ArbitrationMetadataKey.CHAIN_ID.value] = str(chain_id)
        meta[ArbitrationMetadataKey.OUTCOME.value] = (
            decision.outcome.value
        )
        prevailing = decision.prevailing_authority
        if prevailing is not None:
            meta[
                ArbitrationMetadataKey.PREVAILING_AUTHORITY.value
            ] = prevailing.level.value
            meta[
                ArbitrationMetadataKey.PREVAILING_SOURCE_ID.value
            ] = (
                f"{prevailing.source_substrate}:"
                f"{prevailing.source_id}"
            )
        meta[ArbitrationMetadataKey.EVALUATOR_NAMES.value] = list(
            evaluator_names
        )
        meta[ArbitrationMetadataKey.FINDING_COUNT.value] = (
            findings_count
        )
        meta[ArbitrationMetadataKey.CONFLICT_COUNT.value] = (
            conflicts_count
        )
        meta[ArbitrationMetadataKey.DEADLOCK_WITNESS_COUNT.value] = (
            witnesses_count
        )
        meta[ArbitrationMetadataKey.SIGNAL_COUNT.value] = (
            request.case.signal_count
        )
        meta[ArbitrationMetadataKey.RECOMMENDATION_COUNT.value] = (
            request.case.recommendation_count
        )
        meta[ArbitrationMetadataKey.ITERATION_COUNT.value] = (
            request.case.iteration_count
        )
        meta[ArbitrationMetadataKey.MAX_ITERATIONS.value] = (
            request.case.max_iterations
        )
        return meta

    def _runtime_instance_id_for_request(
        self,
        request: ArbitrationRequest,
    ) -> uuid.UUID:
        return derive_runtime_id(
            namespace=_RUNTIME_NAMESPACE,
            tenant_id=request.tenant_id,
            seed_components=(
                "operational_arbitration_runtime",
                self._registry.names(),
                str(request.case.case_id),
            ),
        )

    async def _failed_envelope(
        self,
        *,
        request: ArbitrationRequest,
        resolution: AuthorityResolution,
        evaluation_id: ArbitrationEvaluationId,
        evaluators: Iterable[BaseArbitrationEvaluator],
        started_at: datetime,
        t0: float,
        error: BaseException,
        error_outcome: ArbitrationOutcome,
        reason: str,
        governance_decision_id: uuid.UUID | None = None,
        governance_chain_id: str | None = None,
    ) -> ArbitrationEnvelope:
        # Chronology integrity (Core Law 3): failure envelopes consume
        # a fresh monotonic sequence in the runtime instance just like
        # success envelopes. Reusing `self._sequence` without
        # incrementing produces sequence collisions across failures.
        ended_at = datetime.now(tz=timezone.utc)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        sequence = await self._next_sequence()
        runtime_instance_id = self._runtime_instance_id_for_request(request)
        evaluator_names = tuple(e.name for e in evaluators)
        chain_id = (
            derive_chain_id(evaluator_names=evaluator_names)
            if evaluator_names
            else ArbitrationChainId(
                uuid.UUID("00000000-0000-0000-0000-000000000000")
            )
        )
        trace = ArbitrationTrace(
            evaluation_id=evaluation_id,
            chain_id=chain_id,
            case_id=request.case.case_id,
            runtime_instance_id=runtime_instance_id,
            sequence=sequence,
            outcome=error_outcome,
            evaluator_names=evaluator_names,
            finding_count=0,
            conflict_count=0,
            deadlock_witness_count=0,
            signal_count=request.case.signal_count,
            recommendation_count=request.case.recommendation_count,
            iteration_count=request.case.iteration_count,
            max_iterations=request.case.max_iterations,
            correlation_id=request.correlation_id,
            request_id=request.request_id,
            tenant_id=resolution.tenant_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            error=reason,
            metadata={
                ArbitrationMetadataKey.CASE_ID.value: str(
                    request.case.case_id
                ),
                ArbitrationMetadataKey.EVALUATION_ID.value: str(
                    evaluation_id
                ),
                ArbitrationMetadataKey.OUTCOME.value: (
                    error_outcome.value
                ),
            },
            tenant_authority_source=resolution.source.value,
            governance_decision_id=governance_decision_id,
            governance_chain_id=governance_chain_id,
        )
        return ArbitrationEnvelope(
            trace=trace, result=None, error=error
        )

    # ─── architectural assertions (read-only) ────────────────────────

    # We never define a `dispatch`, `execute`, `retry`, or any
    # mutator method on this class. These no-ops are intentional
    # documentation: tests in tests/test_arbitration_invariants.py
    # assert that no such names appear on the runtime.

    # Authority-level mirror — exposed so callers can read the
    # vocabulary the runtime aggregates against without re-importing
    # the enum from app.arbitration.enums.
    AuthorityLevel = ArbitrationAuthorityLevel


__all__ = ["OperationalArbitrationRuntime"]
