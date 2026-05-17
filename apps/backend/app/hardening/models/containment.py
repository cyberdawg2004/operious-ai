"""`SemanticContainmentTrace` — apex containment-audit summary.

Containment traces are produced by the semantic-overlap
validator. They summarise which boundaries were checked, which
were clean, and which had violations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.hardening.identity import HardeningCorrelationId
from app.hardening.models.violation import (
    BoundaryViolationFinding,
)


@dataclass(frozen=True, slots=True)
class SemanticContainmentTrace:
    """One immutable semantic-containment-audit trace."""

    correlation_id: HardeningCorrelationId
    checked_concerns: tuple[str, ...]
    violations: tuple[BoundaryViolationFinding, ...]
    started_at: datetime
    ended_at: datetime
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.started_at.tzinfo is None:
            raise ValueError(
                "started_at must be timezone-aware"
            )
        if self.ended_at.tzinfo is None:
            raise ValueError(
                "ended_at must be timezone-aware"
            )
        if self.ended_at < self.started_at:
            raise ValueError(
                "ended_at must be >= started_at"
            )

    @property
    def is_contained(self) -> bool:
        return not self.violations


__all__ = ["SemanticContainmentTrace"]
