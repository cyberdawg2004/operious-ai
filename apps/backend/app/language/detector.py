"""Deterministic fail-open language detection."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol, cast

import langdetect
from langdetect import DetectorFactory, LangDetectException


class _LangProbability(Protocol):
    lang: str
    prob: float


_detect = cast(Callable[[str], str], langdetect.detect)  # pyright: ignore[reportUnknownMemberType]
_detect_langs = cast(
    Callable[[str], Sequence[_LangProbability]],
    langdetect.detect_langs,  # pyright: ignore[reportUnknownMemberType]
)

DetectorFactory.seed = 0

SUPPORTED_LANGUAGES = {"ar", "en", "id", "es", "fr", "zh-cn"}


class LanguageDetector:
    """Detects BCP-47 language code from text."""

    def detect(self, text: str) -> str:
        """Return an ISO 639-1 language code, failing open to English."""

        if not text or len(text.strip()) < 10:
            return "en"
        try:
            return _detect(text)
        except LangDetectException:
            return "en"

    def detect_with_confidence(self, text: str) -> tuple[str, float]:
        """Return ``(language, confidence)``, failing open to English."""

        if not text or len(text.strip()) < 10:
            return ("en", 1.0)
        try:
            results = _detect_langs(text)
            if results:
                top = results[0]
                return (str(top.lang), float(top.prob))
            return ("en", 1.0)
        except LangDetectException:
            return ("en", 0.0)
