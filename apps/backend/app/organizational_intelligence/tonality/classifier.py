"""Deterministic baseline tonality classifier.

Pure lexical scoring over a pinned marker catalogue. Two callers
running the same content produce byte-identical tags.

This is **not** an LLM. The substrate's invariant tests forbid
any LLM / network / non-deterministic input here.
"""

from __future__ import annotations

from app.organizational_intelligence.enums import (
    TonalityClass,
    TonalityIntensity,
)
from app.organizational_intelligence.models.tonality import (
    TonalityTag,
)


_MARKERS: dict[
    TonalityClass, tuple[tuple[str, TonalityIntensity], ...]
] = {
    TonalityClass.ESCALATED: (
        ("furious", TonalityIntensity.CRITICAL),
        ("outrageous", TonalityIntensity.HIGH),
        ("unacceptable", TonalityIntensity.HIGH),
        ("escalate", TonalityIntensity.MODERATE),
        ("supervisor", TonalityIntensity.MODERATE),
        ("manager", TonalityIntensity.LOW),
    ),
    TonalityClass.FRUSTRATED: (
        ("angry", TonalityIntensity.HIGH),
        ("frustrated", TonalityIntensity.HIGH),
        ("annoyed", TonalityIntensity.MODERATE),
        ("upset", TonalityIntensity.MODERATE),
        ("disappointed", TonalityIntensity.LOW),
    ),
    TonalityClass.DISTRESSED: (
        ("scared", TonalityIntensity.HIGH),
        ("worried", TonalityIntensity.MODERATE),
        ("anxious", TonalityIntensity.MODERATE),
        ("crying", TonalityIntensity.HIGH),
    ),
    TonalityClass.URGENT: (
        ("urgent", TonalityIntensity.HIGH),
        ("immediately", TonalityIntensity.HIGH),
        ("asap", TonalityIntensity.MODERATE),
        ("now", TonalityIntensity.LOW),
    ),
    TonalityClass.POSITIVE: (
        ("thank you", TonalityIntensity.MODERATE),
        ("thanks", TonalityIntensity.LOW),
        ("appreciate", TonalityIntensity.MODERATE),
        ("great", TonalityIntensity.LOW),
        ("excellent", TonalityIntensity.MODERATE),
    ),
    TonalityClass.CALM: (
        ("please", TonalityIntensity.LOW),
        ("kindly", TonalityIntensity.LOW),
    ),
    TonalityClass.FORMAL: (
        ("dear sir", TonalityIntensity.MODERATE),
        ("dear madam", TonalityIntensity.MODERATE),
        ("regards", TonalityIntensity.LOW),
    ),
    TonalityClass.CASUAL: (
        ("hey", TonalityIntensity.LOW),
        ("cool", TonalityIntensity.LOW),
        ("ok", TonalityIntensity.LOW),
    ),
}


_INTENSITY_WEIGHT: dict[TonalityIntensity, float] = {
    TonalityIntensity.LOW: 0.2,
    TonalityIntensity.MODERATE: 0.45,
    TonalityIntensity.HIGH: 0.7,
    TonalityIntensity.CRITICAL: 0.95,
}


_CLASSIFIER_SIGNATURE = "deterministic.tonality.v1"


class DeterministicTonalityClassifier:
    """Pure lexical tonality classifier."""

    __slots__ = ()

    @property
    def signature(self) -> str:
        return _CLASSIFIER_SIGNATURE

    def classify(self, *, content: str) -> tuple[TonalityTag, ...]:
        body_lower = content.lower()
        tags: list[TonalityTag] = []
        for tonality_class in sorted(
            _MARKERS.keys(), key=lambda c: c.value
        ):
            evidence: list[str] = []
            best_intensity = TonalityIntensity.LOW
            best_score = 0.0
            for marker, intensity in _MARKERS[tonality_class]:
                if marker in body_lower:
                    evidence.append(marker)
                    weight = _INTENSITY_WEIGHT[intensity]
                    if weight > best_score:
                        best_score = weight
                        best_intensity = intensity
            if evidence:
                tags.append(
                    TonalityTag(
                        tonality_class=tonality_class,
                        intensity=best_intensity,
                        confidence=min(
                            1.0,
                            best_score + 0.1 * (len(evidence) - 1),
                        ),
                        evidence=tuple(sorted(evidence)),
                    )
                )
        if not tags:
            tags.append(
                TonalityTag(
                    tonality_class=TonalityClass.NEUTRAL,
                    intensity=TonalityIntensity.LOW,
                    confidence=0.5,
                    evidence=(),
                )
            )
        return tuple(tags)

    @staticmethod
    def select_primary(
        tags: tuple[TonalityTag, ...],
    ) -> TonalityTag:
        """Pick the highest-confidence tag, breaking ties deterministically."""
        if not tags:
            raise ValueError("select_primary requires non-empty tags")
        return max(
            tags,
            key=lambda t: (
                t.confidence,
                _INTENSITY_WEIGHT[t.intensity],
                -ord(t.tonality_class.value[0]),
            ),
        )


__all__ = ["DeterministicTonalityClassifier"]
