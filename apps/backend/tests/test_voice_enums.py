"""Pin voice-substrate wire-format vocabulary."""

from __future__ import annotations

from app.boundary.voice.enums import (
    AudioFormat,
    VoiceDirection,
    VoiceFindingKind,
    VoiceProviderKind,
    VoiceStatus,
    VoiceTraceKind,
)


def test_direction_pinned() -> None:
    assert {member.value for member in VoiceDirection} == {
        "ingress",
        "egress",
    }


def test_status_pinned() -> None:
    assert {member.value for member in VoiceStatus} == {
        "pending",
        "normalized",
        "transcribed",
        "synthesized",
        "completed",
        "rejected",
        "errored",
    }


def test_audio_format_pinned() -> None:
    assert {member.value for member in AudioFormat} == {
        "pcm_s16le",
        "pcm_f32le",
        "opus",
        "mp3",
        "g711_alaw",
        "g711_mulaw",
        "wav",
        "ogg",
        "unknown",
    }


def test_provider_kind_pinned() -> None:
    assert {member.value for member in VoiceProviderKind} == {
        "deterministic_stub",
        "external",
    }


def test_finding_kind_pinned() -> None:
    assert {member.value for member in VoiceFindingKind} == {
        "ok",
        "unverified_provider",
        "low_confidence",
        "empty_transcript",
        "replay_drift",
    }


def test_trace_kind_pinned() -> None:
    assert {member.value for member in VoiceTraceKind} == {
        "ingress_transcribe",
        "egress_synthesize",
        "get_ingress",
        "get_egress",
    }
