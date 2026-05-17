"""Voice-runtime requests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.boundary.voice.enums import AudioFormat
from app.boundary.voice.models.audio import VoiceAudioHandle


@dataclass(frozen=True, slots=True)
class IngressTranscribeRequest:
    """Request to transcribe a customer audio stream."""

    audio: VoiceAudioHandle
    target_language: str
    seed: str
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.target_language:
            raise ValueError(
                "IngressTranscribeRequest.target_language must "
                "be non-empty"
            )
        if not self.seed:
            raise ValueError(
                "IngressTranscribeRequest.seed must be non-empty"
            )


@dataclass(frozen=True, slots=True)
class EgressSynthesizeRequest:
    """Request to synthesize an audio response from canonical text."""

    text: str
    target_language: str
    audio_format: AudioFormat
    sample_rate_hz: int
    seed: str
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.target_language:
            raise ValueError(
                "EgressSynthesizeRequest.target_language must be "
                "non-empty"
            )
        if self.sample_rate_hz <= 0:
            raise ValueError(
                "EgressSynthesizeRequest.sample_rate_hz must be > 0"
            )
        if not self.seed:
            raise ValueError(
                "EgressSynthesizeRequest.seed must be non-empty"
            )


__all__ = [
    "EgressSynthesizeRequest",
    "IngressTranscribeRequest",
]
