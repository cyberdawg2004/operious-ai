"""`VoiceTranscript` — STT output bundle."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.boundary.voice.identity import VoiceTranscriptId
from app.boundary.voice.models.audio import VoiceAudioHandle


@dataclass(frozen=True, slots=True)
class VoiceTranscript:
    """Immutable transcript bundle.

    Attributes:
        transcript_id:           Stable id (UUID5-derivable).
        text:                     Transcribed text.
        language:                 BCP-47 language tag.
        confidence:               STT confidence in ``[0, 1]``.
        provider_name:            STT provider identifier.
        audio_fingerprint:        SHA-256 over the source audio
                                   handle + metadata.
        transcript_fingerprint:   SHA-256 over ``language|text``.
        audio:                    Source audio handle.
        captured_at:              UTC timestamp.
        attributes:               Canonical metadata.
    """

    transcript_id: VoiceTranscriptId
    text: str
    language: str
    confidence: float
    provider_name: str
    audio_fingerprint: str
    transcript_fingerprint: str
    audio: VoiceAudioHandle
    captured_at: datetime
    attributes: dict[str, Any] = field(default_factory=dict[str, Any])

    def __post_init__(self) -> None:
        if not self.language:
            raise ValueError(
                "VoiceTranscript.language must be non-empty"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "VoiceTranscript.confidence must be in [0,1]"
            )
        if not self.provider_name:
            raise ValueError(
                "VoiceTranscript.provider_name must be non-empty"
            )
        if not self.audio_fingerprint:
            raise ValueError(
                "VoiceTranscript.audio_fingerprint must be "
                "non-empty"
            )
        if not self.transcript_fingerprint:
            raise ValueError(
                "VoiceTranscript.transcript_fingerprint must be "
                "non-empty"
            )
        if self.captured_at.tzinfo is None:
            raise ValueError(
                "VoiceTranscript.captured_at must be tz-aware"
            )


__all__ = ["VoiceTranscript"]
