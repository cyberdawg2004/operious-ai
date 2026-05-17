"""`CanonicalLanguageProjection` — canonical-English projection record."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.boundary.translation.enums import CANONICAL_LANGUAGE
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
class CanonicalLanguageProjection:
    """Immutable projection of a customer-language payload into canonical English.

    Attributes:
        source_payload:        Customer-language payload.
        canonical_payload:     Canonical-English payload (always
                                ``language='en'``).
        provider_name:         Translation provider identifier.
        normalization:         Normalisation summary.
        preservation:          Semantic-preservation check.
        canonical_fingerprint: SHA-256 over the canonical text.
        projected_at:          UTC timestamp.
        attributes:            Free-form canonical metadata.
    """

    source_payload: TranslationPayload
    canonical_payload: TranslationPayload
    provider_name: str
    normalization: TranslationNormalization
    preservation: SemanticPreservationCheck
    canonical_fingerprint: str
    projected_at: datetime
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            self.canonical_payload.language
            != CANONICAL_LANGUAGE
        ):
            raise ValueError(
                f"CanonicalLanguageProjection.canonical_payload "
                f"must use the canonical language "
                f"({CANONICAL_LANGUAGE!r})"
            )
        if not self.provider_name:
            raise ValueError(
                "CanonicalLanguageProjection.provider_name "
                "must be non-empty"
            )
        if not self.canonical_fingerprint:
            raise ValueError(
                "CanonicalLanguageProjection.canonical_fingerprint "
                "must be non-empty"
            )
        if self.projected_at.tzinfo is None:
            raise ValueError(
                "CanonicalLanguageProjection.projected_at must be "
                "tz-aware"
            )


__all__ = ["CanonicalLanguageProjection"]
