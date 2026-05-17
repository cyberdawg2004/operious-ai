"""`FindingConflictEvaluator` — pairwise signal-contradiction detection.

Scans every unordered pair of signals in the case. For each pair:

* if the pair is on the same axis (auth/auth or quality/quality) and
  contradicts, emit a `QUALITY_CONFLICT` or `AUTHORISATION_CONFLICT`
  (the kind depends on which axis the pair sits on);
* if the pair crosses axes (e.g. ALLOW vs UNSAFE), emit an
  `AUTHORISATION_QUALITY_CROSS`;
* otherwise no conflict is emitted for the pair.

Each detected conflict is paired with one finding. If no
conflicts are detected and the case has at least two signals, a
single `NO_CONFLICT` finding is emitted at the apex of the
evaluator's output. With fewer than two signals, an
`INSUFFICIENT_SIGNALS` finding is emitted (informational, not an
error).

Determinism: pairs are processed in `(left_index, right_index)`
order over the case's signal tuple.
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
from app.arbitration.taxonomy import (
    ArbitrationFindingCode,
    is_authorisation_verdict,
    is_contradiction,
    is_cross_axis_contradiction,
    is_quality_verdict,
)


class FindingConflictEvaluator(BaseArbitrationEvaluator):
    """Detect contradicting signal verdicts across the case."""

    DEFAULT_NAME = "finding_conflict_evaluator"

    def __init__(self, *, name: str | None = None) -> None:
        super().__init__(name=name or self.DEFAULT_NAME)

    def evaluate(
        self,
        request: ArbitrationRequest,
        *,
        evaluation_id: ArbitrationEvaluationId,
    ) -> ArbitrationEvaluatorOutput:
        signals = request.case.signals
        now = datetime.now(tz=timezone.utc)

        if len(signals) < 2:
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
                    "Case carries fewer than two signals; no "
                    "finding-conflict analysis possible."
                ),
                detected_at=now,
            )
            return ArbitrationEvaluatorOutput(findings=(finding,))

        findings: list[ArbitrationFinding] = []
        conflicts: list[ArbitrationConflict] = []
        ordinal = 0

        for i in range(len(signals)):
            left = signals[i]
            for j in range(i + 1, len(signals)):
                right = signals[j]
                kind = self._classify_pair(left, right)
                if kind is None:
                    continue
                conflict_seed = (
                    f"{evaluation_id}:{self.name}:"
                    f"{left.signal_id}:{right.signal_id}"
                )
                conflict = ArbitrationConflict(
                    conflict_id=derive_conflict_id(seed=conflict_seed),
                    kind=kind,
                    participants=(
                        str(left.signal_id),
                        str(right.signal_id),
                    ),
                    participant_authorities=(
                        left.authority,
                        right.authority,
                    ),
                    summary=(
                        f"{left.verdict.value} vs {right.verdict.value}"
                        f" between {left.source_substrate}"
                        f":{left.source_id} and"
                        f" {right.source_substrate}:{right.source_id}"
                    ),
                )
                conflicts.append(conflict)

                code = (
                    ArbitrationFindingCode.AUTHORISATION_QUALITY_CROSS
                    if kind
                    is ArbitrationConflictKind.AUTHORISATION_QUALITY_CROSS
                    else ArbitrationFindingCode.CONTRADICTORY_FINDINGS
                )
                findings.append(
                    ArbitrationFinding(
                        finding_id=derive_finding_id(
                            evaluation_id=evaluation_id,
                            evaluator_name=self.name,
                            code=code.value,
                            ordinal=ordinal,
                        ),
                        evaluator_name=self.name,
                        outcome_hint=ArbitrationOutcome.ARBITRATION_CONFLICT,
                        code=code.value,
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
                    message="No contradicting verdicts detected.",
                    detected_at=now,
                )
            )

        return ArbitrationEvaluatorOutput(
            findings=tuple(findings),
            conflicts=tuple(conflicts),
        )

    @staticmethod
    def _classify_pair(left, right) -> ArbitrationConflictKind | None:  # type: ignore[no-untyped-def]
        a = left.verdict
        b = right.verdict
        if is_contradiction(a, b):
            if is_authorisation_verdict(a) and is_authorisation_verdict(b):
                return ArbitrationConflictKind.AUTHORISATION_CONFLICT
            if is_quality_verdict(a) and is_quality_verdict(b):
                return ArbitrationConflictKind.QUALITY_CONFLICT
            # Same set says "contradiction" but mixed axes: treat as
            # cross-axis. (This branch is unreachable with the
            # current taxonomy but kept for safety.)
            return ArbitrationConflictKind.AUTHORISATION_QUALITY_CROSS
        if is_cross_axis_contradiction(a, b):
            return ArbitrationConflictKind.AUTHORISATION_QUALITY_CROSS
        return None


__all__ = ["FindingConflictEvaluator"]
