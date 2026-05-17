"""`DeadlockDetectionEvaluator` — bounded deterministic deadlock semantics.

Detection ONLY. The substrate NEVER recovers. The evaluator emits
witnesses + findings; deciding what to do about a witness is the
orchestration layer's responsibility OUTSIDE the arbitration
substrate.

Three deterministic deadlock patterns are surfaced:

1. **ITERATION_EXHAUSTED** — `case.iteration_count >=
   case.max_iterations`. The case has been arbitrated as many times
   as the bound permits; the substrate refuses to interpret as a
   resolvable state.

2. **CYCLIC_CASE_LINEAGE** — `case.prior_case_ids` carries a
   duplicate id (or the current `case_id` reappears in priors).
   The arbitration history references itself; a single-pass scan
   over `prior_case_ids` detects this without recursion.

3. **CONTRADICTORY_ESCALATION_CHAIN** — two ESCALATE signals in the
   case advertise different `escalation_target` metadata values
   while sharing the SAME `source_substrate`. Pattern is observed
   from the current case only; no traversal of historical cases.

`DEADLOCK_RISK` (informational) is surfaced when
`iteration_count > 1` but the case has not yet exhausted its
bound. This warns audit / supervisor surfaces that the case has
been arbitrated more than once without escalating to a full
detection.

The evaluator NEVER performs graph search, distributed deadlock
detection, recursive traversal, or autonomous resolution.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.arbitration.contracts.requests import ArbitrationRequest
from app.arbitration.enums import (
    ArbitrationDeadlockKind,
    ArbitrationOutcome,
    ArbitrationVerdictKind,
)
from app.arbitration.evaluators.base import (
    ArbitrationEvaluatorOutput,
    BaseArbitrationEvaluator,
)
from app.arbitration.identity import (
    ArbitrationEvaluationId,
    derive_deadlock_witness_id,
    derive_finding_id,
)
from app.arbitration.models.deadlock import DeadlockWitness
from app.arbitration.models.findings import ArbitrationFinding
from app.arbitration.taxonomy import ArbitrationFindingCode

ESCALATION_TARGET_METADATA_KEY = "escalation_target"


class DeadlockDetectionEvaluator(BaseArbitrationEvaluator):
    """Bounded deterministic deadlock-pattern detection."""

    DEFAULT_NAME = "deadlock_detection_evaluator"

    def __init__(self, *, name: str | None = None) -> None:
        super().__init__(name=name or self.DEFAULT_NAME)

    def evaluate(
        self,
        request: ArbitrationRequest,
        *,
        evaluation_id: ArbitrationEvaluationId,
    ) -> ArbitrationEvaluatorOutput:
        case = request.case
        now = datetime.now(tz=timezone.utc)

        witnesses: list[DeadlockWitness] = []
        findings: list[ArbitrationFinding] = []
        finding_ordinal = 0
        witness_ordinal = 0

        # ── Pattern 1: iteration exhausted ────────────────────────
        if case.iteration_count >= case.max_iterations:
            witness = DeadlockWitness(
                witness_id=derive_deadlock_witness_id(
                    evaluation_id=evaluation_id,
                    kind=ArbitrationDeadlockKind.ITERATION_EXHAUSTED.value,
                    ordinal=witness_ordinal,
                ),
                kind=ArbitrationDeadlockKind.ITERATION_EXHAUSTED,
                contributing_ids=tuple(
                    str(cid) for cid in case.prior_case_ids
                )
                + (str(case.case_id),),
                summary=(
                    f"iteration_count={case.iteration_count} reached "
                    f"max_iterations={case.max_iterations}"
                ),
                iteration_count=case.iteration_count,
            )
            witnesses.append(witness)
            findings.append(
                ArbitrationFinding(
                    finding_id=derive_finding_id(
                        evaluation_id=evaluation_id,
                        evaluator_name=self.name,
                        code=ArbitrationFindingCode.DEADLOCK_DETECTED.value,
                        ordinal=finding_ordinal,
                    ),
                    evaluator_name=self.name,
                    outcome_hint=ArbitrationOutcome.ARBITRATION_DEADLOCK,
                    code=ArbitrationFindingCode.DEADLOCK_DETECTED.value,
                    message=witness.summary,
                    related_deadlock_witness_id=witness.witness_id,
                    detected_at=now,
                )
            )
            finding_ordinal += 1
            witness_ordinal += 1

        # ── Pattern 2: cyclic case lineage ────────────────────────
        cycle_ids: list[str] = []
        if case.prior_case_ids:
            seen: set[str] = set()
            for prior in case.prior_case_ids:
                key = str(prior)
                if key in seen:
                    cycle_ids.append(key)
                seen.add(key)
            if str(case.case_id) in seen:
                cycle_ids.append(str(case.case_id))
        if cycle_ids:
            witness = DeadlockWitness(
                witness_id=derive_deadlock_witness_id(
                    evaluation_id=evaluation_id,
                    kind=ArbitrationDeadlockKind.CYCLIC_CASE_LINEAGE.value,
                    ordinal=witness_ordinal,
                ),
                kind=ArbitrationDeadlockKind.CYCLIC_CASE_LINEAGE,
                contributing_ids=tuple(cycle_ids),
                summary=(
                    "case lineage contains a duplicate identifier; "
                    "arbitration history references itself."
                ),
                iteration_count=case.iteration_count,
            )
            witnesses.append(witness)
            findings.append(
                ArbitrationFinding(
                    finding_id=derive_finding_id(
                        evaluation_id=evaluation_id,
                        evaluator_name=self.name,
                        code=ArbitrationFindingCode.DEADLOCK_DETECTED.value,
                        ordinal=finding_ordinal,
                    ),
                    evaluator_name=self.name,
                    outcome_hint=ArbitrationOutcome.ARBITRATION_DEADLOCK,
                    code=ArbitrationFindingCode.DEADLOCK_DETECTED.value,
                    message=witness.summary,
                    related_deadlock_witness_id=witness.witness_id,
                    detected_at=now,
                )
            )
            finding_ordinal += 1
            witness_ordinal += 1

        # ── Pattern 3: contradictory escalation chain ─────────────
        escalation_targets_by_source: dict[str, set[str]] = {}
        escalation_signal_ids_by_source: dict[str, list[str]] = {}
        for signal in case.signals:
            if signal.verdict is not ArbitrationVerdictKind.ESCALATE:
                continue
            target = signal.metadata.get(
                ESCALATION_TARGET_METADATA_KEY
            )
            if target is None:
                continue
            bucket = escalation_targets_by_source.setdefault(
                signal.source_substrate, set()
            )
            bucket.add(str(target))
            escalation_signal_ids_by_source.setdefault(
                signal.source_substrate, []
            ).append(str(signal.signal_id))
        for substrate, targets in sorted(
            escalation_targets_by_source.items()
        ):
            if len(targets) < 2:
                continue
            witness = DeadlockWitness(
                witness_id=derive_deadlock_witness_id(
                    evaluation_id=evaluation_id,
                    kind=ArbitrationDeadlockKind.CONTRADICTORY_ESCALATION_CHAIN.value,
                    ordinal=witness_ordinal,
                ),
                kind=ArbitrationDeadlockKind.CONTRADICTORY_ESCALATION_CHAIN,
                contributing_ids=tuple(
                    escalation_signal_ids_by_source[substrate]
                ),
                summary=(
                    f"substrate {substrate!r} escalates to "
                    f"{sorted(targets)!r} simultaneously."
                ),
                iteration_count=case.iteration_count,
            )
            witnesses.append(witness)
            findings.append(
                ArbitrationFinding(
                    finding_id=derive_finding_id(
                        evaluation_id=evaluation_id,
                        evaluator_name=self.name,
                        code=ArbitrationFindingCode.DEADLOCK_DETECTED.value,
                        ordinal=finding_ordinal,
                    ),
                    evaluator_name=self.name,
                    outcome_hint=ArbitrationOutcome.ARBITRATION_DEADLOCK,
                    code=ArbitrationFindingCode.DEADLOCK_DETECTED.value,
                    message=witness.summary,
                    related_deadlock_witness_id=witness.witness_id,
                    detected_at=now,
                )
            )
            finding_ordinal += 1
            witness_ordinal += 1

        # ── DEADLOCK_RISK informational finding ────────────────────
        if not witnesses and case.iteration_count > 1:
            findings.append(
                ArbitrationFinding(
                    finding_id=derive_finding_id(
                        evaluation_id=evaluation_id,
                        evaluator_name=self.name,
                        code=ArbitrationFindingCode.DEADLOCK_RISK.value,
                        ordinal=finding_ordinal,
                    ),
                    evaluator_name=self.name,
                    outcome_hint=ArbitrationOutcome.ARBITRATION_INCONCLUSIVE,
                    code=ArbitrationFindingCode.DEADLOCK_RISK.value,
                    message=(
                        f"case has been arbitrated "
                        f"{case.iteration_count} times without "
                        f"a deadlock pattern; bound is "
                        f"{case.max_iterations}."
                    ),
                    detected_at=now,
                )
            )

        if not findings:
            findings.append(
                ArbitrationFinding(
                    finding_id=derive_finding_id(
                        evaluation_id=evaluation_id,
                        evaluator_name=self.name,
                        code=ArbitrationFindingCode.NO_CONFLICT.value,
                        ordinal=0,
                    ),
                    evaluator_name=self.name,
                    outcome_hint=ArbitrationOutcome.ARBITRATION_RESOLVED,
                    code=ArbitrationFindingCode.NO_CONFLICT.value,
                    message="No deadlock pattern detected.",
                    detected_at=now,
                )
            )

        return ArbitrationEvaluatorOutput(
            findings=tuple(findings),
            deadlock_witnesses=tuple(witnesses),
        )


__all__ = ["DeadlockDetectionEvaluator"]
