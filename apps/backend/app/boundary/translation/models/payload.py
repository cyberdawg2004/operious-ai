"""`TranslationPayload` — immutable text payload + language tag."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TranslationPayload:
    """One immutable, language-tagged text payload.

    Attributes:
        text:        The actual text. Whitespace is normalised
                      separately by the `Normalizer`.
        language:    BCP-47 language tag (e.g. ``"en"``,
                      ``"es-MX"``).
        attributes:  Optional canonical metadata payload.
    """

    text: str
    language: str
    attributes: dict[str, Any] = field(default_factory=dict[str, Any])

    def __post_init__(self) -> None:
        if not self.language:
            raise ValueError(
                "TranslationPayload.language must be non-empty"
            )
        if "\x00" in self.text:
            raise ValueError(
                "TranslationPayload.text contains NUL bytes"
            )


__all__ = ["TranslationPayload"]
