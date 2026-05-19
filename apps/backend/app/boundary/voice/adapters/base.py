"""Abstract STT + TTS provider interfaces.

Voice providers convert audio to text (ingress) and text to
audio (egress). The interface is intentionally minimal:

* providers MUST be async and pure with respect to inputs;
* providers MUST NOT mutate global state, retry, or schedule;
* providers MUST be replaceable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.boundary.voice.enums import VoiceProviderKind
from app.boundary.voice.models.audio import VoiceAudioHandle


# ─── STT ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SpeechToTextProviderRequest:
    audio: VoiceAudioHandle
    target_language: str

    def __post_init__(self) -> None:
        if not self.target_language:
            raise ValueError(
                "SpeechToTextProviderRequest.target_language must "
                "be non-empty"
            )


@dataclass(frozen=True, slots=True)
class SpeechToTextProviderResponse:
    transcript: str
    language: str
    confidence: float
    provider_name: str

    def __post_init__(self) -> None:
        if not self.language:
            raise ValueError(
                "SpeechToTextProviderResponse.language must be "
                "non-empty"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "SpeechToTextProviderResponse.confidence must be "
                "in [0,1]"
            )
        if not self.provider_name:
            raise ValueError(
                "SpeechToTextProviderResponse.provider_name must "
                "be non-empty"
            )


class BaseSpeechToTextProvider(ABC):
    """Abstract STT provider."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def kind(self) -> VoiceProviderKind: ...

    @abstractmethod
    async def transcribe(
        self, request: SpeechToTextProviderRequest
    ) -> SpeechToTextProviderResponse: ...


# ─── TTS ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TextToSpeechProviderRequest:
    text: str
    target_language: str
    audio_format: str
    sample_rate_hz: int

    def __post_init__(self) -> None:
        if not self.target_language:
            raise ValueError(
                "TextToSpeechProviderRequest.target_language must "
                "be non-empty"
            )
        if not self.audio_format:
            raise ValueError(
                "TextToSpeechProviderRequest.audio_format must be "
                "non-empty"
            )
        if self.sample_rate_hz <= 0:
            raise ValueError(
                "TextToSpeechProviderRequest.sample_rate_hz must "
                "be > 0"
            )


@dataclass(frozen=True, slots=True)
class TextToSpeechProviderResponse:
    audio: VoiceAudioHandle
    provider_name: str

    def __post_init__(self) -> None:
        if not self.provider_name:
            raise ValueError(
                "TextToSpeechProviderResponse.provider_name must "
                "be non-empty"
            )


class BaseTextToSpeechProvider(ABC):
    """Abstract TTS provider."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def kind(self) -> VoiceProviderKind: ...

    @abstractmethod
    async def synthesize(
        self, request: TextToSpeechProviderRequest
    ) -> TextToSpeechProviderResponse: ...


__all__ = [
    "BaseSpeechToTextProvider",
    "BaseTextToSpeechProvider",
    "SpeechToTextProviderRequest",
    "SpeechToTextProviderResponse",
    "TextToSpeechProviderRequest",
    "TextToSpeechProviderResponse",
]
