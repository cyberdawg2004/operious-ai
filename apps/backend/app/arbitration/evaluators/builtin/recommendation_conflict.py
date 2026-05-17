"""`RecommendationConflictEvaluator` — pairwise directive contradictions.

Scans every unordered pair of recommendations. A pair is in
conflict iff the two directives differ (case-sensitive equality).
The substrate does NOT parse the directive — it treats it as
opaque text. This deliberately surfaces any non-identical pair of
recommendations as inspectable state; the substrate refuses to
silently merge or rank directives.

Determinism: pairs are processed in
`(left_index, right_index)` order over the case's recommendation
tuple.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.arbitration.contracts.requests import ArbitrationRequest
from app.arbitration.enums import (
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


class RecommendationConflictEvaluator(BaseArbitrationEvaluator):
    """Detect contradicting recommendation directives across the case."""

    DEFAULT_NAME = "recommendation_conflict_evaluator"

    def __init__(self, *, name: str | None = None) -> None:
        super().__init__(name=name or self.DEFAULT_NAME)

    def evaluate(
        self,
        request: ArbitrationRequest,
        *,
        evaluation_id: ArbitrationEvaluationId,
    ) -> ArbitrationEvaluatorOutput:
        recs = request.case.recommendations
        now = datetime.now(tz=timezone.utc)

        if len(recs) < 2:
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
                    "Case carries fewer than two recommendations; "
                    "no directive-conflict analysis possible."
                ),
                detected_at=now,
            )
            return ArbitrationEvaluatorOutput(findings=(finding,))

        findings: list[ArbitrationFinding] = []
        conflicts: list[ArbitrationConflict] = []
        ordinal = 0

        for i in range(len(recs)):
            left = recs[i]
            for j in range(i + 1, len(recs)):
                right = recs[j]
                if left.directive == right.directive:
                    continue
                seed = (
                    f"{evaluation_id}:{self.name}:"
                    f"{left.recommendation_id}:{right.recommendation_id}"
                )
                conflict = ArbitrationConflict(
                    conflict_id=derive_conflict_id(seed=seed),
                    kind=ArbitrationConflictKind.RECOMMENDATION_CONFLICT,
                    participants=(
                        str(left.recommendation_id),
                        str(right.recommendation_id),
                    ),
                    participant_authorities=(
                        left.authority,
                        right.authority,
                    ),
                    summary=(
                        f"recommendation {left.directive!r} vs "
                        f"{right.directive!r} between "
                        f"{left.source_substrate}:{left.source_id} "
                        f"and {right.source_substrate}:{right.source_id}"
                    ),
                )
                conflicts.append(conflict)
                findings.append(
                    ArbitrationFinding(
                        finding_id=derive_finding_id(
                            evaluation_id=evaluation_id,
                            evaluator_name=self.name,
                            code=ArbitrationFindingCode.CONFLICTING_RECOMMENDATIONS.value,
                            ordinal=ordinal,
                        ),
                        evaluator_name=self.name,
                        outcome_hint=ArbitrationOutcome.ARBITRATION_CONFLICT,
                        code=ArbitrationFindingCode.CONFLICTING_RECOMMENDATIONS.value,
                        message=conflict.summary,
                        related_conflict_id=conflict.conflict_id,
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
                    message="All recommendation directives agree.",
                    detected_at=now,
                )
            )

        return ArbitrationEvaluatorOutput(
            findings=tuple(findings),
            conflicts=tuple(conflicts),
        )


__all__ = ["RecommendationConflictEvaluator"]
