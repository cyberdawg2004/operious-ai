"""`EscalationConflictEvaluator` — escalation-specific contradictions.

A specialised lens over signals. It surfaces:

* ESCALATE vs ALLOW pairs (a substrate wants to escalate while
  another permits proceeding — the operational ambiguity is the
  state of interest),
* ESCALATE vs ESCALATE pairs whose `metadata` carries a
  conflicting ``escalation_target`` (two substrates escalate to
  different targets simultaneously).

Determinism: pairs are processed in `(left_index, right_index)`
order over the case's signal tuple. The ESCALATE vs ESCALATE
target-mismatch sub-case relies on the caller having populated
each signal's metadata with an ``escalation_target`` key; if the
metadata is absent the substrate does NOT infer a target.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.arbitration.contracts.requests import ArbitrationRequest
from app.arbitration.enums import (
    ArbitrationConflictKind,
    ArbitrationOutcome,
    ArbitrationVerdictKind,
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
from app.arbitration.models.signal import ArbitrationSignal
from app.arbitration.taxonomy import ArbitrationFindingCode

# Metadata key the substrate inspects on each signal to surface
# target-mismatched escalations. Other metadata is ignored.
ESCALATION_TARGET_METADATA_KEY = "escalation_target"


class EscalationConflictEvaluator(BaseArbitrationEvaluator):
    """Detect escalation-specific contradictions across signals."""

    DEFAULT_NAME = "escalation_conflict_evaluator"

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

        # Two-pass: find escalations first; if none, short-circuit.
        escalations = tuple(
            s
            for s in signals
            if s.verdict is ArbitrationVerdictKind.ESCALATE
        )
        if not escalations:
            finding = ArbitrationFinding(
                finding_id=derive_finding_id(
                    evaluation_id=evaluation_id,
                    evaluator_name=self.name,
                    code=ArbitrationFindingCode.NO_CONFLICT.value,
                    ordinal=0,
                ),
                evaluator_name=self.name,
                outcome_hint=ArbitrationOutcome.ARBITRATION_RESOLVED,
                code=ArbitrationFindingCode.NO_CONFLICT.value,
                message="No escalation signals present.",
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
                kind = self._classify(left, right)
                if kind is None:
                    continue
                seed = (
                    f"{evaluation_id}:{self.name}:"
                    f"{left.signal_id}:{right.signal_id}"
                )
                conflict = ArbitrationConflict(
                    conflict_id=derive_conflict_id(seed=seed),
                    kind=kind,
                    participants=(
                        str(left.signal_id),
                        str(right.signal_id),
                    ),
                    participant_authorities=(
                        left.authority,
                        right.authority,
                    ),
                    summary=self._summary(left, right, kind),
                )
                conflicts.append(conflict)
                findings.append(
                    ArbitrationFinding(
                        finding_id=derive_finding_id(
                            evaluation_id=evaluation_id,
                            evaluator_name=self.name,
                            code=ArbitrationFindingCode.ESCALATION_CONFLICT.value,
                            ordinal=ordinal,
                        ),
                        evaluator_name=self.name,
                        outcome_hint=ArbitrationOutcome.ARBITRATION_CONFLICT,
                        code=ArbitrationFindingCode.ESCALATION_CONFLICT.value,
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
                    outcome_hint=ArbitrationOutcome.ARBITRATION_ESCALATED,
                    code=ArbitrationFindingCode.NO_CONFLICT.value,
                    message=(
                        "Escalation signals present and consistent."
                    ),
                    detected_at=now,
                )
            )

        return ArbitrationEvaluatorOutput(
            findings=tuple(findings),
            conflicts=tuple(conflicts),
        )

    @staticmethod
    def _classify(
        left: ArbitrationSignal,
        right: ArbitrationSignal,
    ) -> ArbitrationConflictKind | None:
        if (
            left.verdict is ArbitrationVerdictKind.ESCALATE
            and right.verdict is ArbitrationVerdictKind.ALLOW
        ) or (
            right.verdict is ArbitrationVerdictKind.ESCALATE
            and left.verdict is ArbitrationVerdictKind.ALLOW
        ):
            return ArbitrationConflictKind.ESCALATION_CONFLICT
        if (
            left.verdict is ArbitrationVerdictKind.ESCALATE
            and right.verdict is ArbitrationVerdictKind.ESCALATE
        ):
            left_target = left.metadata.get(
                ESCALATION_TARGET_METADATA_KEY
            )
            right_target = right.metadata.get(
                ESCALATION_TARGET_METADATA_KEY
            )
            if (
                left_target is not None
                and right_target is not None
                and left_target != right_target
            ):
                return ArbitrationConflictKind.ESCALATION_CONFLICT
        return None

    @staticmethod
    def _summary(
        left: ArbitrationSignal,
        right: ArbitrationSignal,
        kind: ArbitrationConflictKind,
    ) -> str:
        if (
            left.verdict is ArbitrationVerdictKind.ESCALATE
            and right.verdict is ArbitrationVerdictKind.ESCALATE
        ):
            left_target = left.metadata.get(
                ESCALATION_TARGET_METADATA_KEY
            )
            right_target = right.metadata.get(
                ESCALATION_TARGET_METADATA_KEY
            )
            return (
                f"escalation target mismatch: "
                f"{left.source_substrate}:{left.source_id}→{left_target!r}"
                f" vs "
                f"{right.source_substrate}:{right.source_id}→{right_target!r}"
            )
        return (
            f"escalation vs proceed: "
            f"{left.source_substrate}:{left.source_id}={left.verdict.value}"
            f" vs "
            f"{right.source_substrate}:{right.source_id}={right.verdict.value}"
            f" (kind={kind.value})"
        )


__all__ = [
    "EscalationConflictEvaluator",
    "ESCALATION_TARGET_METADATA_KEY",
]
