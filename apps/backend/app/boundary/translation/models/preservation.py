"""`SemanticPreservationCheck` — observational equivalence record."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.boundary.translation.enums import (
    SemanticPreservationStatus,
)


@dataclass(frozen=True, slots=True)
class SemanticPreservationCheck:
    """One immutable semantic-preservation record.

    The check verifies whether a translation pair preserves the
    operational semantics that MUST NOT be altered (e.g. governance
    keywords like 'escalate', 'block', 'approve', 'deny', etc.).

    The check is observational. It does not rewrite or correct
    translations.
    """

    status: SemanticPreservationStatus
    summary: str
    detected_at: datetime
    canonical_tokens_present: tuple[str, ...]
    canonical_tokens_missing: tuple[str, ...]
    introduced_governance_tokens: tuple[str, ...]
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.summary:
            raise ValueError(
                "SemanticPreservationCheck.summary must be non-empty"
            )
        if self.detected_at.tzinfo is None:
            raise ValueError(
                "SemanticPreservationCheck.detected_at must be tz-aware"
            )

    @property
    def is_preserved(self) -> bool:
        return (
            self.status
            is SemanticPreservationStatus.PRESERVED
        )


__all__ = ["SemanticPreservationCheck"]
