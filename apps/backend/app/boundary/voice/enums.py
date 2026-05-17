"""Voice-substrate wire-format vocabulary.

Voice is **boundary infrastructure**. It MUST NEVER influence
governance, mutate cognition, change operational meaning, or
inject orchestration logic.

Pinned wire values are guarded by
`tests/test_voice_invariants.py`.
"""

from __future__ import annotations

from enum import StrEnum


class VoiceDirection(StrEnum):
    INGRESS = "ingress"
    EGRESS = "egress"


class VoiceStatus(StrEnum):
    """Lifecycle of a voice envelope."""

    PENDING = "pending"
    NORMALIZED = "normalized"
    TRANSCRIBED = "transcribed"
    SYNTHESIZED = "synthesized"
    COMPLETED = "completed"
    REJECTED = "rejected"
    ERRORED = "errored"


class VoiceProviderKind(StrEnum):
    DETERMINISTIC_STUB = "deterministic_stub"
    EXTERNAL = "external"


class AudioFormat(StrEnum):
    """Bounded vocabulary of audio container/codec hints."""

    PCM_S16LE = "pcm_s16le"
    PCM_F32LE = "pcm_f32le"
    OPUS = "opus"
    MP3 = "mp3"
    G711_ALAW = "g711_alaw"
    G711_MULAW = "g711_mulaw"
    WAV = "wav"
    OGG = "ogg"
    UNKNOWN = "unknown"


class VoiceFindingKind(StrEnum):
    OK = "ok"
    UNVERIFIED_PROVIDER = "unverified_provider"
    LOW_CONFIDENCE = "low_confidence"
    EMPTY_TRANSCRIPT = "empty_transcript"
    REPLAY_DRIFT = "replay_drift"


class VoiceTraceKind(StrEnum):
    INGRESS_TRANSCRIBE = "ingress_transcribe"
    EGRESS_SYNTHESIZE = "egress_synthesize"
    GET_INGRESS = "get_ingress"
    GET_EGRESS = "get_egress"


__all__ = [
    "AudioFormat",
    "VoiceDirection",
    "VoiceFindingKind",
    "VoiceProviderKind",
    "VoiceStatus",
    "VoiceTraceKind",
]
