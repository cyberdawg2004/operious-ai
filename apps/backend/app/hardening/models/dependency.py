"""Dependency-audit models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.hardening.enums import (
    HardeningSeverity,
    SubstrateName,
)
from app.hardening.identity import (
    DependencyAuditId,
    HardeningFindingId,
)


@dataclass(frozen=True, slots=True)
class DependencyEdge:
    """Directed dependency edge (source → target)."""

    source: SubstrateName
    target: SubstrateName
    occurrences: int

    def __post_init__(self) -> None:
        if self.source == self.target:
            raise ValueError(
                "DependencyEdge.source must differ from .target"
            )
        if self.occurrences < 1:
            raise ValueError(
                "DependencyEdge.occurrences must be >= 1"
            )


@dataclass(frozen=True, slots=True)
class DependencyAuditFinding:
    """One immutable dependency-audit finding.

    The auditor produces an inventory of cross-substrate edges
    plus a list of edges the canonical authority-ownership map
    flags as forbidden.
    """

    finding_id: HardeningFindingId
    audit_id: DependencyAuditId
    edges: tuple[DependencyEdge, ...]
    forbidden_edges: tuple[DependencyEdge, ...]
    severity: HardeningSeverity
    summary: str
    detected_at: datetime
    attributes: dict[str, Any] = field(default_factory=dict[str, Any])

    def __post_init__(self) -> None:
        if not self.summary:
            raise ValueError(
                "DependencyAuditFinding.summary must be non-empty"
            )
        if self.detected_at.tzinfo is None:
            raise ValueError(
                "DependencyAuditFinding.detected_at must be "
                "tz-aware"
            )

    @property
    def is_clean(self) -> bool:
        return not self.forbidden_edges


__all__ = ["DependencyAuditFinding", "DependencyEdge"]
