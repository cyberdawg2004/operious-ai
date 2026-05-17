"""Pure replay verification — fingerprint-equivalence over `TranslationReplay`."""

from __future__ import annotations

from app.boundary.translation.models.replay import (
    TranslationReplay,
)
from app.boundary.translation.serializers.canonical import (
    text_fingerprint,
)


def verify_translation_replay(
    *,
    replay: TranslationReplay,
    canonical_text: str,
    canonical_language: str,
    boundary_text: str,
    boundary_language: str,
) -> bool:
    """Return True iff the recorded fingerprints reproduce.

    The verifier never re-executes the provider. It only
    recomputes the deterministic fingerprints and compares
    them.
    """
    canonical_fp = text_fingerprint(
        canonical_text, language=canonical_language
    )
    boundary_fp = text_fingerprint(
        boundary_text, language=boundary_language
    )
    return (
        canonical_fp == replay.canonical_fingerprint
        and boundary_fp == replay.boundary_fingerprint
    )


__all__ = ["verify_translation_replay"]
