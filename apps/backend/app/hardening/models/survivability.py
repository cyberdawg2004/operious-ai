"""Survivability finding."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.hardening.enums import SurvivabilityStatus
from app.hardening.identity import HardeningFindingId


@dataclass(frozen=True, slots=True)
class SurvivabilityFinding:
    """One immutable survivability finding.

    Attributes:
        finding_id:        Stable id.
        status:            Outcome classification.
        survived_count:    How many records survived a
                            persistence-continuity check.
        expected_count:    How many records were expected.
        scope:             Free-form scope hint.
        detected_at:       UTC timestamp.
        attributes:        Canonical metadata.
    """

    finding_id: HardeningFindingId
    status: SurvivabilityStatus
    survived_count: int
    expected_count: int
    scope: str | None
    detected_at: datetime
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.survived_count < 0:
            raise ValueError(
                "survived_count must be non-negative"
            )
        if self.expected_count < 0:
            raise ValueError(
                "expected_count must be non-negative"
            )
        if self.survived_count > self.expected_count:
            raise ValueError(
                "survived_count cannot exceed expected_count"
            )
        if self.detected_at.tzinfo is None:
            raise ValueError(
                "SurvivabilityFinding.detected_at must be tz-aware"
            )


__all__ = ["SurvivabilityFinding"]
