"""`VoiceSynthesis` — TTS output bundle."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.boundary.voice.identity import VoiceSynthesisId
from app.boundary.voice.models.audio import VoiceAudioHandle


@dataclass(frozen=True, slots=True)
class VoiceSynthesis:
    """Immutable TTS output bundle.

    Attributes:
        synthesis_id:           Stable id.
        source_text:             Canonical-language text.
        target_language:         Synthesised audio language.
        provider_name:           TTS provider identifier.
        text_fingerprint:        SHA-256 over source text.
        audio_fingerprint:       SHA-256 over the produced audio
                                  handle + metadata.
        audio:                   Produced audio handle.
        captured_at:             UTC timestamp.
        attributes:              Canonical metadata.
    """

    synthesis_id: VoiceSynthesisId
    source_text: str
    target_language: str
    provider_name: str
    text_fingerprint: str
    audio_fingerprint: str
    audio: VoiceAudioHandle
    captured_at: datetime
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.target_language:
            raise ValueError(
                "VoiceSynthesis.target_language must be non-empty"
            )
        if not self.provider_name:
            raise ValueError(
                "VoiceSynthesis.provider_name must be non-empty"
            )
        if not self.text_fingerprint:
            raise ValueError(
                "VoiceSynthesis.text_fingerprint must be non-empty"
            )
        if not self.audio_fingerprint:
            raise ValueError(
                "VoiceSynthesis.audio_fingerprint must be non-empty"
            )
        if self.captured_at.tzinfo is None:
            raise ValueError(
                "VoiceSynthesis.captured_at must be tz-aware"
            )


__all__ = ["VoiceSynthesis"]
