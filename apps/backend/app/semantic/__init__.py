"""Semantic utilities for deterministic local computation."""

from app.semantic.fingerprinting import (
    FINGERPRINT_VERSION,
    NGRAM_SIZE,
    NUM_HASH_FUNCTIONS,
    TextFingerprinter,
)

__all__ = [
    "FINGERPRINT_VERSION",
    "NGRAM_SIZE",
    "NUM_HASH_FUNCTIONS",
    "TextFingerprinter",
]
