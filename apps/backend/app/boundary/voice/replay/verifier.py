"""Pure replay verification for voice events."""

from __future__ import annotations

from app.boundary.voice.models.audio import VoiceAudioHandle
from app.boundary.voice.models.replay import VoiceReplay
from app.boundary.voice.serializers.canonical import (
    audio_handle_fingerprint,
    transcript_fingerprint,
)


def verify_voice_replay(
    *,
    replay: VoiceReplay,
    audio: VoiceAudioHandle,
    transcript: str | None,
    transcript_language: str | None,
) -> bool:
    """Recompute deterministic fingerprints; compare to recorded values."""
    audio_fp = audio_handle_fingerprint(
        handle=audio.handle,
        audio_format=audio.audio_format.value,
        sample_rate_hz=audio.sample_rate_hz,
        duration_ms=audio.duration_ms,
        language=audio.language,
    )
    if audio_fp != replay.audio_fingerprint:
        return False
    if transcript is None:
        return replay.transcript_fingerprint is None
    if transcript_language is None:
        return False
    transcript_fp = transcript_fingerprint(
        transcript=transcript,
        language=transcript_language,
    )
    return transcript_fp == replay.transcript_fingerprint


__all__ = ["verify_voice_replay"]
