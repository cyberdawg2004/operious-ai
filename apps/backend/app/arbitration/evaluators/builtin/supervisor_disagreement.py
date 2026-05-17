"""`SupervisorDisagreementEvaluator` — read-only supervisor disagreement.

Supervisors are read-only evaluators (platform architectural
contract). They may emit different verdicts and / or different
recommendation directives for the same case. That disagreement
must become **inspectable operational state**, not hidden
evaluator behaviour.

This evaluator considers ONLY signals / recommendations whose
`authority is ArbitrationAuthorityLevel.SUPERVISOR`. It surfaces:

* signal verdict disagreement (any two supervisor signals whose
  verdicts differ — strictly stricter than the
  finding-conflict evaluator because supervisor disagreement is
  itself an audit signal independent of formal contradiction),
* directive disagreement (any two supervisor recommendations
  whose directives differ).

Determinism: pairs processed in input order over the filtered
supervisor signal / recommendation tuples.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.arbitration.contracts.requests import ArbitrationRequest
from app.arbitration.enums import (
    ArbitrationAuthorityLevel,
    ArbitrationConflictKind,
    ArbitrationOutcome,
)
from app.arbitration.evaluators.base import (
    ArbitrationEvaluatorOutput,
    BaseArbitrationEvaluator,
)
from app.arbitration.identity import (
    ArbitrationEvaluationId,
    derive_conflict_id,
    derive_finding_id,
)
from app.arbitration.models.conflict import ArbitrationConflict
from app.arbitration.models.findings import ArbitrationFinding
from app.arbitration.taxonomy import ArbitrationFindingCode


class SupervisorDisagreementEvaluator(BaseArbitrationEvaluator):
    """Surface disagreements between supervisor-authority inputs."""

    DEFAULT_NAME = "supervisor_disagreement_evaluator"

    def __init__(self, *, name: str | None = None) -> None:
        super().__init__(name=name or self.DEFAULT_NAME)

    def evaluate(
        self,
        request: ArbitrationRequest,
        *,
        evaluation_id: ArbitrationEvaluationId,
    ) -> ArbitrationEvaluatorOutput:
        now = datetime.now(tz=timezone.utc)
        supervisor_signals = tuple(
            s
            for s in request.case.signals
            if s.authority is ArbitrationAuthorityLevel.SUPERVISOR
        )
        supervisor_recs = tuple(
            r
            for r in request.case.recommendations
            if r.authority is ArbitrationAuthorityLevel.SUPERVISOR
        )

        if len(supervisor_signals) + len(supervisor_recs) < 2:
            finding = ArbitrationFinding(
                finding_id=derive_finding_id(
                    evaluation_id=evaluation_id,
                    evaluator_name=self.name,
                    code=ArbitrationFindingCode.INSUFFICIENT_SIGNALS.value,
                    ordinal=0,
                ),
                evaluator_name=self.name,
                outcome_hint=ArbitrationOutcome.ARBITRATION_INCONCLUSIVE,
                code=ArbitrationFindingCode.INSUFFICIENT_SIGNALS.value,
                message=(
                    "Fewer than two supervisor inputs; no "
                    "disagreement analysis possible."
                ),
                authority=ArbitrationAuthorityLevel.SUPERVISOR,
                detected_at=now,
            )
            return ArbitrationEvaluatorOutput(findings=(finding,))

        findings: list[ArbitrationFinding] = []
        conflicts: list[ArbitrationConflict] = []
        ordinal = 0

        # Signal-vs-signal supervisor disagreement.
        for i in range(len(supervisor_signals)):
            left = supervisor_signals[i]
            for j in range(i + 1, len(supervisor_signals)):
                right = supervisor_signals[j]
                if left.verdict is right.verdict:
                    continue
                seed = (
                    f"{evaluation_id}:{self.name}:sig:"
                    f"{left.signal_id}:{right.signal_id}"
                )
                conflict = ArbitrationConflict(
                    conflict_id=derive_conflict_id(seed=seed),
                    kind=ArbitrationConflictKind.SUPERVISOR_DISAGREEMENT,
                    participants=(
                        str(left.signal_id),
                        str(right.signal_id),
                    ),
                    participant_authorities=(
                        left.authority,
                        right.authority,
                    ),
                    summary=(
                        f"supervisor verdict disagreement: "
                        f"{left.source_id}={left.verdict.value} vs "
                        f"{right.source_id}={right.verdict.value}"
                    ),
                )
                conflicts.append(conflict)
                findings.append(
                    ArbitrationFinding(
                        finding_id=derive_finding_id(
                            evaluation_id=evaluation_id,
                            evaluator_name=self.name,
                            code=ArbitrationFindingCode.SUPERVISOR_DISAGREEMENT.value,
                            ordinal=ordinal,
                        ),
                        evaluator_name=self.name,
                        outcome_hint=ArbitrationOutcome.ARBITRATION_CONFLICT,
                        code=ArbitrationFindingCode.SUPERVISOR_DISAGREEMENT.value,
                        message=conflict.summary,
                        related_conflict_id=conflict.conflict_id,
                        authority=ArbitrationAuthorityLevel.SUPERVISOR,
                        detected_at=now,
                    )
                )
                ordinal += 1

        # Recommendation-vs-recommendation supervisor disagreement.
        for i in range(len(supervisor_recs)):
            left_r = supervisor_recs[i]
            for j in range(i + 1, len(supervisor_recs)):
                right_r = supervisor_recs[j]
                if left_r.directive == right_r.directive:
                    continue
                seed = (
                    f"{evaluation_id}:{self.name}:rec:"
                    f"{left_r.recommendation_id}:"
                    f"{right_r.recommendation_id}"
                )
                conflict = ArbitrationConflict(
                    conflict_id=derive_conflict_id(seed=seed),
                    kind=ArbitrationConflictKind.SUPERVISOR_DISAGREEMENT,
                    participants=(
                        str(left_r.recommendation_id),
                        str(right_r.recommendation_id),
                    ),
                    participant_authorities=(
                        left_r.authority,
                        right_r.authority,
                    ),
                    summary=(
                        f"supervisor directive disagreement: "
                        f"{left_r.source_id}={left_r.directive!r} vs "
                        f"{right_r.source_id}={right_r.directive!r}"
                    ),
                )
                conflicts.append(conflict)
                findings.append(
                    ArbitrationFinding(
                        finding_id=derive_finding_id(
                            evaluation_id=evaluation_id,
                            evaluator_name=self.name,
                            code=ArbitrationFindingCode.SUPERVISOR_DISAGREEMENT.value,
                            ordinal=ordinal,
                        ),
                        evaluator_name=self.name,
                        outcome_hint=ArbitrationOutcome.ARBITRATION_CONFLICT,
                        code=ArbitrationFindingCode.SUPERVISOR_DISAGREEMENT.value,
                        message=conflict.summary,
                        related_conflict_id=conflict.conflict_id,
                        authority=ArbitrationAuthorityLevel.SUPERVISOR,
                        detected_at=now,
                    )
                )
                ordinal += 1

        if not conflicts:
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
                    message="Supervisor inputs agree.",
                    authority=ArbitrationAuthorityLevel.SUPERVISOR,
                    detected_at=now,
                )
            )

        return ArbitrationEvaluatorOutput(
            findings=tuple(findings),
            conflicts=tuple(conflicts),
        )


__all__ = ["SupervisorDisagreementEvaluator"]
