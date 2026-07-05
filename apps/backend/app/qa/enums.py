"""QA scoring vocabulary."""

from __future__ import annotations

from enum import StrEnum


class QAScoreDimension(StrEnum):
    """Closed score dimensions emitted by the QA agent."""

    DIAGNOSTIC_ACCURACY = "diagnostic_accuracy"
    POLICY_COMPLIANCE = "policy_compliance"
    TIMELINE_INTEGRITY = "timeline_integrity"
    RESOLUTION_QUALITY = "resolution_quality"
    SEMANTIC_GROUNDING = "semantic_grounding"


QA_SCORE_DIMENSIONS: tuple[QAScoreDimension, ...] = (
    QAScoreDimension.DIAGNOSTIC_ACCURACY,
    QAScoreDimension.POLICY_COMPLIANCE,
    QAScoreDimension.TIMELINE_INTEGRITY,
    QAScoreDimension.RESOLUTION_QUALITY,
    QAScoreDimension.SEMANTIC_GROUNDING,
)


class SemanticGroundingVerdict(StrEnum):
    """LLM semantic grounding quality verdict for a reply+citation pair.

    STRONG:   Citations directly support the claims made in the reply.
    ADEQUATE: Citations partially support the claims; minor gaps acceptable.
    WEAK:     Citations only loosely relate to the claims; grounding unclear.
    MISSING:  No citations, or citations are entirely irrelevant to the reply.
    """

    STRONG = "STRONG"
    ADEQUATE = "ADEQUATE"
    WEAK = "WEAK"
    MISSING = "MISSING"


__all__ = [
    "QA_SCORE_DIMENSIONS",
    "QAScoreDimension",
    "SemanticGroundingVerdict",
]
