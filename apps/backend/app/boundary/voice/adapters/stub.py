"""Deterministic STT + TTS stub providers.

These providers are intentionally **non-magic**. They derive
output deterministically from the input handle so that:

* tests can verify replay equivalence;
* CI does not depend on external services;
* the substrate's invariants can be proved without a real provider.

Real STT/TTS providers belong outside the substrate. They MUST
be wrapped by deterministic normalisation + content-cache
layers before being substituted in.
"""

from __future__ import annotations

import hashlib

from app.boundary.voice.enums import (
    AudioFormat,
    VoiceProviderKind,
)
from app.boundary.voice.models.audio import VoiceAudioHandle
from app.boundary.voice.adapters.base import (
    BaseSpeechToTextProvider,
    BaseTextToSpeechProvider,
    SpeechToTextProviderRequest,
    SpeechToTextProviderResponse,
    TextToSpeechProviderRequest,
    TextToSpeechProviderResponse,
)


# A canonical lookup table — for stub purposes only.
_STUB_TRANSCRIPT_PREFIX = "stub-transcript:"


class DeterministicStubSpeechToTextProvider(
    BaseSpeechToTextProvider
):
    """Deterministic STT stub.

    The transcript is reconstructed from a deterministic
    fingerprint of the handle. The provider also honours an
    optional ``transcript`` attribute on the audio handle: this
    lets tests inject a known-good transcript without breaking
    determinism.
    """

    __slots__ = ("_name", "_confidence")

    def __init__(
        self,
        *,
        name: str = "deterministic-stub-stt",
        confidence: float = 1.0,
    ) -> None:
        if not name:
            raise ValueError(
                "DeterministicStubSpeechToTextProvider.name must "
                "be non-empty"
            )
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(
                "DeterministicStubSpeechToTextProvider.confidence "
                "must be in [0,1]"
            )
        self._name = name
        self._confidence = confidence

    @property
    def name(self) -> str:
        return self._name

    @property
    def kind(self) -> VoiceProviderKind:
        return VoiceProviderKind.DETERMINISTIC_STUB

    async def transcribe(
        self, request: SpeechToTextProviderRequest
    ) -> SpeechToTextProviderResponse:
        baked = request.audio.attributes.get("transcript")
        if isinstance(baked, str) and baked:
            text = baked
        else:
            text = (
                f"{_STUB_TRANSCRIPT_PREFIX}"
                f"{hashlib.sha256(request.audio.handle.encode()).hexdigest()[:16]}"
            )
        return SpeechToTextProviderResponse(
            transcript=text,
            language=request.target_language,
            confidence=self._confidence,
            provider_name=self._name,
        )


class DeterministicStubTextToSpeechProvider(
    BaseTextToSpeechProvider
):
    """Deterministic TTS stub.

    Returns a synthetic audio handle derived from a hash of the
    text + language + format. This is sufficient to verify
    replay-equivalence without producing real audio data.
    """

    __slots__ = ("_name",)

    def __init__(
        self, *, name: str = "deterministic-stub-tts"
    ) -> None:
        if not name:
            raise ValueError(
                "DeterministicStubTextToSpeechProvider.name must "
                "be non-empty"
            )
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def kind(self) -> VoiceProviderKind:
        return VoiceProviderKind.DETERMINISTIC_STUB

    async def synthesize(
        self, request: TextToSpeechProviderRequest
    ) -> TextToSpeechProviderResponse:
        digest = hashlib.sha256(
            (
                f"{request.target_language}\x1f{request.audio_format}\x1f"
                f"{request.sample_rate_hz}\x1f{request.text}"
            ).encode("utf-8")
        ).hexdigest()
        try:
            fmt = AudioFormat(request.audio_format)
        except ValueError as exc:
            raise ValueError(
                f"unsupported audio_format "
                f"{request.audio_format!r} (allowed: "
                f"{[f.value for f in AudioFormat]})"
            ) from exc
        handle = VoiceAudioHandle(
            handle=f"stub-audio:{digest}",
            audio_format=fmt,
            sample_rate_hz=request.sample_rate_hz,
            duration_ms=max(1, len(request.text) * 50),
            language=request.target_language,
        )
        return TextToSpeechProviderResponse(
            audio=handle,
            provider_name=self._name,
        )


__all__ = [
    "DeterministicStubSpeechToTextProvider",
    "DeterministicStubTextToSpeechProvider",
]
