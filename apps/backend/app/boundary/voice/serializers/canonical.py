"""Canonical fingerprinting for voice artifacts.

The voice substrate does NOT store raw audio inside its
deterministic envelopes. It stores **handles** (e.g. content
URIs, blob fingerprints) that point to the byte-stream stored
elsewhere. Fingerprinting operates on the handle plus its
metadata, not the audio bytes themselves.
"""

from __future__ import annotations

import hashlib


def audio_handle_fingerprint(
    *,
    handle: str,
    audio_format: str,
    sample_rate_hz: int,
    duration_ms: int,
    language: str,
) -> str:
    if not handle:
        raise ValueError(
            "audio_handle_fingerprint.handle must be non-empty"
        )
    if not audio_format:
        raise ValueError(
            "audio_handle_fingerprint.audio_format must be non-empty"
        )
    if sample_rate_hz <= 0:
        raise ValueError(
            "audio_handle_fingerprint.sample_rate_hz must be > 0"
        )
    if duration_ms < 0:
        raise ValueError(
            "audio_handle_fingerprint.duration_ms must be >= 0"
        )
    if not language:
        raise ValueError(
            "audio_handle_fingerprint.language must be non-empty"
        )
    blob = (
        f"{handle}\x1f{audio_format}\x1f{sample_rate_hz}\x1f"
        f"{duration_ms}\x1f{language}"
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def transcript_fingerprint(
    *, transcript: str, language: str
) -> str:
    if not language:
        raise ValueError(
            "transcript_fingerprint.language must be non-empty"
        )
    blob = f"{language}\x1f{transcript}".encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


__all__ = [
    "audio_handle_fingerprint",
    "transcript_fingerprint",
]
