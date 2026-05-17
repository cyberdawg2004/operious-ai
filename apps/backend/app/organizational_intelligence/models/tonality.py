"""Tonality classification value objects.

Tonality is **descriptive metadata**. Every output is a tag, not a
directive. Communication policy lives in the communication-pattern
substrate (which only retrieves APPROVED patterns).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.organizational_intelligence.enums import (
    TonalityClass,
    TonalityIntensity,
)
from app.organizational_intelligence.identity import (
    TonalityAnalysisId,
)


@dataclass(frozen=True, slots=True)
class TonalityTag:
    """One bounded tonality classification."""

    tonality_class: TonalityClass
    intensity: TonalityIntensity
    confidence: float
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "TonalityTag.confidence must be in [0.0, 1.0]"
            )


@dataclass(frozen=True, slots=True)
class TonalityAnalysis:
    """Apex immutable tonality-analysis record."""

    analysis_id: TonalityAnalysisId
    content_fingerprint: str
    tags: tuple[TonalityTag, ...]
    primary_tag: TonalityTag
    analyzed_at: datetime
    analyzer_signature: str
    correlation_hint: str | None = None
    tenant_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tags:
            raise ValueError(
                "TonalityAnalysis must contain at least one tag"
            )
        if self.primary_tag not in self.tags:
            raise ValueError(
                "TonalityAnalysis.primary_tag must be in tags"
            )
        if self.analyzed_at.tzinfo is None:
            raise ValueError(
                "TonalityAnalysis.analyzed_at must be tz-aware"
            )
        if not self.analyzer_signature:
            raise ValueError(
                "TonalityAnalysis.analyzer_signature must be "
                "non-empty"
            )
        if not self.content_fingerprint:
            raise ValueError(
                "TonalityAnalysis.content_fingerprint must be "
                "non-empty"
            )


__all__ = ["TonalityAnalysis", "TonalityTag"]
