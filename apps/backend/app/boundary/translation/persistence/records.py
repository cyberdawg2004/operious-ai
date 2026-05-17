"""Persistence records for translation events."""

from __future__ import annotations

from dataclasses import dataclass

from app.boundary.translation.models.canonical import (
    CanonicalLanguageProjection,
)
from app.boundary.translation.models.identity import (
    TranslationIdentity,
)
from app.boundary.translation.models.lineage import (
    TranslationLineageEntry,
)
from app.boundary.translation.models.localization import (
    LocalizationMetadata,
)
from app.boundary.translation.models.replay import (
    TranslationReplay,
)
from app.boundary.translation.models.validation import (
    TranslationValidation,
)


@dataclass(frozen=True, slots=True)
class IngressTranslationRecord:
    """Write-once persistence record for one ingress translation."""

    identity: TranslationIdentity
    projection: CanonicalLanguageProjection
    validation: TranslationValidation
    lineage_entry: TranslationLineageEntry
    replay: TranslationReplay


@dataclass(frozen=True, slots=True)
class EgressLocalizationRecord:
    """Write-once persistence record for one egress localisation."""

    identity: TranslationIdentity
    localization: LocalizationMetadata
    validation: TranslationValidation
    lineage_entry: TranslationLineageEntry
    replay: TranslationReplay


__all__ = [
    "EgressLocalizationRecord",
    "IngressTranslationRecord",
]
