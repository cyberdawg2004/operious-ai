"""`VoiceAudioHandle` — opaque handle + metadata for an audio stream.

Operious never stores raw audio bytes inside deterministic
envelopes. Audio data lives in external blob storage; the
substrate only carries an opaque handle and the metadata
required for replay-safe identification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.boundary.voice.enums import AudioFormat


@dataclass(frozen=True, slots=True)
class VoiceAudioHandle:
    """Replay-safe descriptor of an audio stream."""

    handle: str
    audio_format: AudioFormat
    sample_rate_hz: int
    duration_ms: int
    language: str
    attributes: dict[str, Any] = field(default_factory=dict[str, Any])

    def __post_init__(self) -> None:
        if not self.handle:
            raise ValueError(
                "VoiceAudioHandle.handle must be non-empty"
            )
        if self.sample_rate_hz <= 0:
            raise ValueError(
                "VoiceAudioHandle.sample_rate_hz must be > 0"
            )
        if self.duration_ms < 0:
            raise ValueError(
                "VoiceAudioHandle.duration_ms must be >= 0"
            )
        if not self.language:
            raise ValueError(
                "VoiceAudioHandle.language must be non-empty"
            )


__all__ = ["VoiceAudioHandle"]
