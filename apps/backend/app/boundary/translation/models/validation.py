"""`TranslationValidation` — apex validation record.

Combines the normalisation, semantic-preservation, and replay
records into one inspectable artifact. Validation is
observational — it never auto-corrects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.boundary.translation.enums import (
    SemanticPreservationStatus,
    TranslationFindingKind,
    TranslationStatus,
)
from app.boundary.translation.models.normalization import (
    TranslationNormalization,
)
from app.boundary.translation.models.preservation import (
    SemanticPreservationCheck,
)


@dataclass(frozen=True, slots=True)
class TranslationFinding:
    """One immutable observational translation finding."""

    ordinal: int
    kind: TranslationFindingKind
    summary: str
    evidence: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError(
                "TranslationFinding.ordinal must be >= 0"
            )
        if not self.summary:
            raise ValueError(
                "TranslationFinding.summary must be non-empty"
            )


@dataclass(frozen=True, slots=True)
class TranslationValidation:
    """Apex validation record for one translation operation.

    Attributes:
        status:                Lifecycle status.
        normalization:         Normalisation summary.
        preservation:          Semantic-preservation check.
        findings:              Sorted observational findings.
        validated_at:          UTC timestamp.
        attributes:            Canonical metadata payload.
    """

    status: TranslationStatus
    normalization: TranslationNormalization
    preservation: SemanticPreservationCheck
    findings: tuple[TranslationFinding, ...]
    validated_at: datetime
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.validated_at.tzinfo is None:
            raise ValueError(
                "TranslationValidation.validated_at must be tz-aware"
            )
        prev = -1
        for f in self.findings:
            if f.ordinal <= prev:
                raise ValueError(
                    "TranslationValidation.findings must be "
                    "strictly monotonic by ordinal"
                )
            prev = f.ordinal

    @property
    def is_clean(self) -> bool:
        return (
            self.preservation.status
            is SemanticPreservationStatus.PRESERVED
            and not self.findings
        )


__all__ = [
    "TranslationFinding",
    "TranslationValidation",
]
