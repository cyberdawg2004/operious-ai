"""`LocalizationMetadata` — egress localisation evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.boundary.translation.enums import (
    LocalizationFormality,
)
from app.boundary.translation.models.normalization import (
    TranslationNormalization,
)
from app.boundary.translation.models.payload import (
    TranslationPayload,
)
from app.boundary.translation.models.preservation import (
    SemanticPreservationCheck,
)


@dataclass(frozen=True, slots=True)
class LocalizationMetadata:
    """Immutable egress localisation record.

    Attributes:
        canonical_payload:    The canonical-English payload that
                               was localised.
        localized_payload:    The localised customer-language
                               payload.
        provider_name:        Translation provider identifier.
        formality:            Bounded formality classification.
        normalization:        Normalisation summary.
        preservation:         Semantic-preservation check.
        localized_at:         UTC timestamp.
        attributes:           Canonical metadata payload.
    """

    canonical_payload: TranslationPayload
    localized_payload: TranslationPayload
    provider_name: str
    formality: LocalizationFormality
    normalization: TranslationNormalization
    preservation: SemanticPreservationCheck
    localized_at: datetime
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider_name:
            raise ValueError(
                "LocalizationMetadata.provider_name must be non-empty"
            )
        if self.localized_at.tzinfo is None:
            raise ValueError(
                "LocalizationMetadata.localized_at must be tz-aware"
            )


__all__ = ["LocalizationMetadata"]
