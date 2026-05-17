"""`BoundaryNormalizer` — pure deterministic text normalisation.

Applied at the boundary BEFORE translation so canonical
fingerprints are reproducible. The normaliser:

* applies Unicode NFC,
* trims leading/trailing whitespace,
* collapses runs of whitespace to single spaces,
* preserves NUL-byte rejection,
* records every applied step.

Normalisation is observational. It NEVER alters semantic
content (it does not rewrite tokens, translate content, or
modify governance markers).
"""

from __future__ import annotations

import unicodedata

from app.boundary.translation.models.normalization import (
    TranslationNormalization,
)
from app.boundary.translation.serializers.canonical import (
    text_fingerprint,
)


def normalize_text(
    text: str, *, language: str
) -> tuple[str, TranslationNormalization]:
    """Return ``(normalised_text, normalization_record)``."""
    if "\x00" in text:
        raise ValueError(
            "BoundaryNormalizer.text contains NUL bytes"
        )
    if not language:
        raise ValueError(
            "BoundaryNormalizer.language must be non-empty"
        )

    original_fp = text_fingerprint(text, language=language)
    steps: list[str] = []

    nfc = unicodedata.normalize("NFC", text)
    if nfc != text:
        steps.append("nfc")

    trimmed = nfc.strip()
    if trimmed != nfc:
        steps.append("trim")

    collapsed = _collapse_whitespace(trimmed)
    if collapsed != trimmed:
        steps.append("collapse_whitespace")

    normalised_fp = text_fingerprint(
        collapsed, language=language
    )

    return collapsed, TranslationNormalization(
        original_fingerprint=original_fp,
        normalized_fingerprint=normalised_fp,
        normalised_length=len(collapsed),
        steps=tuple(steps),
    )


def _collapse_whitespace(text: str) -> str:
    out: list[str] = []
    last_space = False
    for ch in text:
        if ch.isspace():
            if not last_space:
                out.append(" ")
                last_space = True
        else:
            out.append(ch)
            last_space = False
    return "".join(out)


class BoundaryNormalizer:
    """Stateless object form of `normalize_text`."""

    __slots__ = ()

    def normalize(
        self, text: str, *, language: str
    ) -> tuple[str, TranslationNormalization]:
        return normalize_text(text, language=language)


__all__ = ["BoundaryNormalizer", "normalize_text"]
