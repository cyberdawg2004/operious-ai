"""Pure deterministic scoring helpers.

These are intentionally simple, **deterministic** baselines.
They exist so the substrate has a non-empty, byte-stable scoring
pipeline that downstream callers can swap with richer heuristics
later — but that swap MUST be deterministic too.
"""

from __future__ import annotations

from app.organizational_intelligence.enums import (
    CommunicationPatternKind,
    SopFindingSeverity,
    TonalityClass,
)
from app.organizational_intelligence.models.communication import (
    CommunicationPattern,
)


_FINDING_WEIGHT: dict[SopFindingSeverity, float] = {
    SopFindingSeverity.INFO: 0.1,
    SopFindingSeverity.LOW: 0.25,
    SopFindingSeverity.MEDIUM: 0.5,
    SopFindingSeverity.HIGH: 0.75,
    SopFindingSeverity.CRITICAL: 1.0,
}

_CLASS_TO_PREFERRED_KINDS: dict[
    TonalityClass, tuple[CommunicationPatternKind, ...]
] = {
    TonalityClass.NEUTRAL: (
        CommunicationPatternKind.ACKNOWLEDGEMENT,
        CommunicationPatternKind.INFORMATION_DELIVERY,
    ),
    TonalityClass.CALM: (
        CommunicationPatternKind.ACKNOWLEDGEMENT,
        CommunicationPatternKind.INFORMATION_DELIVERY,
    ),
    TonalityClass.URGENT: (
        CommunicationPatternKind.ACKNOWLEDGEMENT,
        CommunicationPatternKind.INFORMATION_DELIVERY,
    ),
    TonalityClass.FRUSTRATED: (
        CommunicationPatternKind.EMPATHY,
        CommunicationPatternKind.DE_ESCALATION,
        CommunicationPatternKind.APOLOGY,
    ),
    TonalityClass.ESCALATED: (
        CommunicationPatternKind.DE_ESCALATION,
        CommunicationPatternKind.ESCALATION_HANDOFF,
        CommunicationPatternKind.APOLOGY,
    ),
    TonalityClass.DISTRESSED: (
        CommunicationPatternKind.EMPATHY,
        CommunicationPatternKind.DE_ESCALATION,
    ),
    TonalityClass.POSITIVE: (
        CommunicationPatternKind.CLOSURE,
        CommunicationPatternKind.ACKNOWLEDGEMENT,
    ),
    TonalityClass.FORMAL: (
        CommunicationPatternKind.INFORMATION_DELIVERY,
        CommunicationPatternKind.ACKNOWLEDGEMENT,
    ),
    TonalityClass.CASUAL: (
        CommunicationPatternKind.ACKNOWLEDGEMENT,
        CommunicationPatternKind.EMPATHY,
    ),
}


def finding_severity_weight(severity: SopFindingSeverity) -> float:
    """Return the canonical numeric weight of a finding severity."""
    return _FINDING_WEIGHT[severity]


def candidate_strength(
    *,
    occurrence_count: int,
    evidence_count: int,
) -> float:
    """Deterministic baseline strength score for a candidate pattern.

    Formula: ``min(1.0, 0.1 * occurrence_count + 0.05 * evidence_count)``.
    Pure, byte-stable, replay-equivalent.
    """
    if occurrence_count < 0 or evidence_count < 0:
        raise ValueError(
            "candidate_strength requires non-negative inputs"
        )
    raw = 0.1 * occurrence_count + 0.05 * evidence_count
    return min(1.0, max(0.0, raw))


def score_communication_match(
    *,
    primary_class: TonalityClass,
    pattern: CommunicationPattern,
) -> tuple[float, str]:
    """Deterministic match score between a tonality class and a pattern.

    Pure rules:

    * Pattern must list ``primary_class`` in ``applicable_classes``.
    * Patterns whose ``kind`` is in the preferred-kinds tuple for
      the class score higher.
    * Ties broken by sorting ``handle`` ascending (caller's
      responsibility).
    """
    if primary_class not in pattern.applicable_classes:
        return 0.0, "primary_class_not_applicable"
    preferred = _CLASS_TO_PREFERRED_KINDS.get(primary_class, ())
    if pattern.kind in preferred:
        ordinal = preferred.index(pattern.kind)
        score = 1.0 - 0.1 * ordinal
        return max(0.5, score), f"preferred_kind:{pattern.kind.value}"
    return 0.5, "applicable_only"


__all__ = [
    "candidate_strength",
    "finding_severity_weight",
    "score_communication_match",
]
