"""Voice domain-model invariants."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.boundary.voice.enums import (
    AudioFormat,
    VoiceDirection,
)
from app.boundary.voice.identity import (
    derive_event_id,
    derive_lineage_id,
    derive_replay_id,
    derive_synthesis_id,
    derive_transcript_id,
    generate_correlation_id,
)
from app.boundary.voice.models.audio import VoiceAudioHandle
from app.boundary.voice.models.identity_bundle import (
    VoiceIdentity,
)
from app.boundary.voice.models.lineage import (
    VoiceLineage,
    VoiceLineageEntry,
)
from app.boundary.voice.models.replay import VoiceReplay
from app.boundary.voice.models.synthesis import VoiceSynthesis
from app.boundary.voice.models.transcript import (
    VoiceTranscript,
)


NOW = datetime.now(UTC)


def test_audio_handle_validates() -> None:
    with pytest.raises(ValueError):
        VoiceAudioHandle(
            handle="",
            audio_format=AudioFormat.OPUS,
            sample_rate_hz=16000,
            duration_ms=100,
            language="es",
        )
    with pytest.raises(ValueError):
        VoiceAudioHandle(
            handle="x",
            audio_format=AudioFormat.OPUS,
            sample_rate_hz=0,
            duration_ms=100,
            language="es",
        )


def test_voice_transcript_confidence_bounds() -> None:
    audio = VoiceAudioHandle(
        handle="x",
        audio_format=AudioFormat.OPUS,
        sample_rate_hz=16000,
        duration_ms=100,
        language="es",
    )
    with pytest.raises(ValueError):
        VoiceTranscript(
            transcript_id=derive_transcript_id(seed="t"),
            text="hi",
            language="es",
            confidence=1.5,
            provider_name="p",
            audio_fingerprint="a" * 64,
            transcript_fingerprint="b" * 64,
            audio=audio,
            captured_at=NOW,
        )


def test_voice_synthesis_validates() -> None:
    audio = VoiceAudioHandle(
        handle="x",
        audio_format=AudioFormat.OPUS,
        sample_rate_hz=16000,
        duration_ms=100,
        language="es",
    )
    with pytest.raises(ValueError):
        VoiceSynthesis(
            synthesis_id=derive_synthesis_id(seed="s"),
            source_text="hi",
            target_language="es",
            provider_name="",
            text_fingerprint="x",
            audio_fingerprint="y",
            audio=audio,
            captured_at=NOW,
        )


def test_voice_lineage_must_be_strictly_monotonic() -> None:
    with pytest.raises(ValueError):
        VoiceLineage(
            lineage_id=derive_lineage_id(seed="l"),
            correlation_id=generate_correlation_id(),
            entries=(
                VoiceLineageEntry(
                    sequence=0,
                    direction=VoiceDirection.INGRESS,
                    audio_fingerprint="a",
                    transcript_fingerprint="b",
                    provider_name="p",
                    seed="s",
                ),
                VoiceLineageEntry(
                    sequence=0,
                    direction=VoiceDirection.EGRESS,
                    audio_fingerprint="a",
                    transcript_fingerprint="b",
                    provider_name="p",
                    seed="s",
                ),
            ),
        )


def test_voice_replay_validates() -> None:
    rep = VoiceReplay(
        replay_id=derive_replay_id(seed="r"),
        seed="r",
        audio_fingerprint="a" * 64,
        transcript_fingerprint=None,
        provider_name="p",
        captured_at=NOW,
    )
    assert rep.transcript_fingerprint is None


def test_voice_identity_requires_seed() -> None:
    with pytest.raises(ValueError):
        VoiceIdentity(
            event_id=derive_event_id(seed="x"),
            lineage_id=derive_lineage_id(seed="y"),
            correlation_id=generate_correlation_id(),
            seed="",
        )
