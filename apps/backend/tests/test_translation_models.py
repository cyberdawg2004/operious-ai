"""Translation domain-model invariants."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.boundary.translation.enums import (
    LocalizationFormality,
    SemanticPreservationStatus,
)
from app.boundary.translation.identity import (
    derive_translation_id,
)
from app.boundary.translation.models.canonical import (
    CanonicalLanguageProjection,
)
from app.boundary.translation.models.localization import (
    LocalizationMetadata,
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


NOW = datetime.now(UTC)


def _normalisation() -> TranslationNormalization:
    return TranslationNormalization(
        original_fingerprint="a" * 64,
        normalized_fingerprint="a" * 64,
        normalised_length=10,
        steps=("nfc",),
    )


def _preservation_clean() -> SemanticPreservationCheck:
    return SemanticPreservationCheck(
        status=SemanticPreservationStatus.PRESERVED,
        summary="ok",
        detected_at=NOW,
        canonical_tokens_present=(),
        canonical_tokens_missing=(),
        introduced_governance_tokens=(),
    )


def test_translation_payload_rejects_empty_language() -> None:
    with pytest.raises(ValueError):
        TranslationPayload(text="hi", language="")


def test_translation_payload_rejects_nul_bytes() -> None:
    with pytest.raises(ValueError):
        TranslationPayload(text="\x00", language="en")


def test_canonical_projection_must_be_english() -> None:
    with pytest.raises(ValueError):
        CanonicalLanguageProjection(
            source_payload=TranslationPayload(
                text="x", language="es"
            ),
            canonical_payload=TranslationPayload(
                text="x", language="es"
            ),
            provider_name="p",
            normalization=_normalisation(),
            preservation=_preservation_clean(),
            canonical_fingerprint="abc",
            projected_at=NOW,
        )


def test_canonical_projection_accepts_english() -> None:
    proj = CanonicalLanguageProjection(
        source_payload=TranslationPayload(
            text="hola", language="es"
        ),
        canonical_payload=TranslationPayload(
            text="hello", language="en"
        ),
        provider_name="p",
        normalization=_normalisation(),
        preservation=_preservation_clean(),
        canonical_fingerprint="abc",
        projected_at=NOW,
    )
    assert proj.canonical_payload.language == "en"


def test_localization_metadata_requires_provider_name() -> None:
    with pytest.raises(ValueError):
        LocalizationMetadata(
            canonical_payload=TranslationPayload(
                text="x", language="en"
            ),
            localized_payload=TranslationPayload(
                text="x", language="es"
            ),
            provider_name="",
            formality=LocalizationFormality.NEUTRAL,
            normalization=_normalisation(),
            preservation=_preservation_clean(),
            localized_at=NOW,
        )


def test_translation_id_is_deterministic() -> None:
    a = derive_translation_id(seed="abc")
    b = derive_translation_id(seed="abc")
    assert a == b
