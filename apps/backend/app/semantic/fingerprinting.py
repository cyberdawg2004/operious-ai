"""Deterministic MinHash text fingerprinting."""

from __future__ import annotations

import re
from typing import Final

import mmh3

NUM_HASH_FUNCTIONS: Final[int] = 128
NGRAM_SIZE: Final[int] = 3
FINGERPRINT_VERSION: Final[str] = "minhash_128_3gram_v1"
_HASH_SEEDS: Final[tuple[int, ...]] = tuple(range(NUM_HASH_FUNCTIONS))
_ZERO_SIGNATURE: Final[tuple[int, ...]] = tuple(0 for _ in _HASH_SEEDS)


class TextFingerprinter:
    """
    MinHash text fingerprinting.
    128 hash functions, 3-gram tokenization.
    Deterministic: same text always returns same signature.
    Target: < 5ms per call on typical ticket text.
    """

    def fingerprint(self, text: str) -> tuple[int, ...]:
        """
        Returns a 128-element MinHash signature.
        Returns tuple of 128 zeros for empty/short text.
        Never raises.
        """
        try:
            normalized = self._normalize(text)
            shingles = self._shingle(normalized)
            if not shingles:
                return _ZERO_SIGNATURE

            return tuple(
                min(mmh3.hash(shingle, seed, signed=False) for shingle in shingles)
                for seed in _HASH_SEEDS
            )
        except Exception:  # noqa: BLE001
            return _ZERO_SIGNATURE

    def jaccard_similarity(
        self,
        sig_a: tuple[int, ...],
        sig_b: tuple[int, ...],
    ) -> float:
        """
        Estimate Jaccard similarity from two MinHash signatures.
        Returns 0.0 if signatures are empty or mismatched length.
        """
        if not sig_a or not sig_b or len(sig_a) != len(sig_b):
            return 0.0
        matches = sum(a == b for a, b in zip(sig_a, sig_b))
        return matches / len(sig_a)

    def _normalize(self, text: str) -> str:
        text = text.lower()
        text = re.sub(r"\s+", " ", text.strip())
        text = re.sub(r"[^\w\s]", "", text)
        return text

    def _shingle(self, text: str) -> list[str]:
        tokens = text.split()
        if len(tokens) < NGRAM_SIZE:
            return []
        return [
            " ".join(tokens[i : i + NGRAM_SIZE])
            for i in range(len(tokens) - NGRAM_SIZE + 1)
        ]
