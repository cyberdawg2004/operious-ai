"""Operational-pattern observation + analysis models.

Pattern analysis is **observation only**. It surfaces recurring
operational issues (escalation failures, SOP conflicts,
communication degradation, drift) but never auto-fixes them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.organizational_intelligence.enums import (
    OperationalPatternKind,
)
from app.organizational_intelligence.identity import (
    OperationalPatternAnalysisId,
    OperationalPatternObservationId,
)


@dataclass(frozen=True, slots=True)
class OperationalPatternObservation:
    """One immutable operational observation.

    Observations are the substrate's INPUT to pattern analysis.
    They are deterministic projections of upstream substrate
    artifacts (e.g. session timelines, supervisor evaluations,
    governance findings) — but the substrate **never imports**
    those typed shapes; observations carry opaque string handles.
    """

    observation_id: OperationalPatternObservationId
    seed: str
    kind: OperationalPatternKind
    summary: str
    occurrence_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    evidence: tuple[str, ...] = ()
    tenant_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.occurrence_count < 1:
            raise ValueError(
                "occurrence_count must be >= 1"
            )
        if not self.summary:
            raise ValueError(
                "OperationalPatternObservation.summary must be "
                "non-empty"
            )
        if self.first_seen_at.tzinfo is None:
            raise ValueError(
                "first_seen_at must be timezone-aware"
            )
        if self.last_seen_at.tzinfo is None:
            raise ValueError(
                "last_seen_at must be timezone-aware"
            )
        if self.last_seen_at < self.first_seen_at:
            raise ValueError(
                "last_seen_at must be >= first_seen_at"
            )


@dataclass(frozen=True, slots=True)
class OperationalPatternAnalysis:
    """Result of analysing a batch of observations.

    The analysis is **inspectable**. Recommendations are
    optionally produced downstream by `RecommendationRuntime`.
    """

    analysis_id: OperationalPatternAnalysisId
    seed: str
    analyzed_at: datetime
    analyzer_signature: str
    observations: tuple[OperationalPatternObservation, ...]
    summary: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.analyzed_at.tzinfo is None:
            raise ValueError(
                "OperationalPatternAnalysis.analyzed_at must be "
                "tz-aware"
            )
        if not self.analyzer_signature:
            raise ValueError(
                "OperationalPatternAnalysis.analyzer_signature "
                "must be non-empty"
            )


__all__ = [
    "OperationalPatternAnalysis",
    "OperationalPatternObservation",
]
