"""QA scoring vocabulary."""

from __future__ import annotations

from enum import StrEnum


class QAScoreDimension(StrEnum):
    """Closed score dimensions emitted by the QA agent."""

    DIAGNOSTIC_ACCURACY = "diagnostic_accuracy"
    POLICY_COMPLIANCE = "policy_compliance"
    TIMELINE_INTEGRITY = "timeline_integrity"
    RESOLUTION_QUALITY = "resolution_quality"


QA_SCORE_DIMENSIONS: tuple[QAScoreDimension, ...] = (
    QAScoreDimension.DIAGNOSTIC_ACCURACY,
    QAScoreDimension.POLICY_COMPLIANCE,
    QAScoreDimension.TIMELINE_INTEGRITY,
    QAScoreDimension.RESOLUTION_QUALITY,
)


__all__ = ["QA_SCORE_DIMENSIONS", "QAScoreDimension"]
