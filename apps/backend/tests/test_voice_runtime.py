"""End-to-end tests for the voice runtime."""

from __future__ import annotations

import pytest

from app.boundary.voice import (
    AudioFormat,
    DeterministicStubSpeechToTextProvider,
    DeterministicStubTextToSpeechProvider,
    EgressSynthesizeRequest,
    EgressSynthesizeResult,
    InMemoryVoicePersistence,
    IngressTranscribeResult,
    IngressTranscribeRequest,
    VoiceAudioHandle,
    VoiceContainmentError,
    VoiceDirection,
    VoiceEgressRuntime,
    VoiceIngressRuntime,
    VoiceRuntime,
    verify_voice_replay,
)


@pytest.fixture()
def runtime() -> VoiceRuntime:
    persistence = InMemoryVoicePersistence()
    stt = DeterministicStubSpeechToTextProvider()
    tts = DeterministicStubTextToSpeechProvider()
    return VoiceRuntime(
        ingress=VoiceIngressRuntime(
            provider=stt, persistence=persistence
        ),
        egress=VoiceEgressRuntime(
            provider=tts, persistence=persistence
        ),
    )


@pytest.mark.asyncio
async def test_ingress_transcribe_uses_baked_transcript(
    runtime: VoiceRuntime,
) -> None:
    audio = VoiceAudioHandle(
        handle="blob:1",
        audio_format=AudioFormat.OPUS,
        sample_rate_hz=16000,
        duration_ms=2000,
        language="es",
        attributes={"transcript": "Hola, necesito ayuda"},
    )
    env = await runtime.ingress.transcribe(
        IngressTranscribeRequest(
            audio=audio,
            target_language="es",
            seed="v1",
            correlation_id="conv-1",
        )
    )
    assert env.is_ok
    assert isinstance(env.result, IngressTranscribeResult)
    assert env.result.transcript is not None
    assert (
        env.result.transcript.text
        == "Hola, necesito ayuda"
    )


@pytest.mark.asyncio
async def test_ingress_rejects_operational_directive(
    runtime: VoiceRuntime,
) -> None:
    audio = VoiceAudioHandle(
        handle="blob:2",
        audio_format=AudioFormat.OPUS,
        sample_rate_hz=16000,
        duration_ms=1000,
        language="es",
        attributes={"operational_directive": True},
    )
    env = await runtime.ingress.transcribe(
        IngressTranscribeRequest(
            audio=audio,
            target_language="es",
            seed="v2",
        )
    )
    assert env.error is not None
    assert isinstance(env.error, VoiceContainmentError)


@pytest.mark.asyncio
async def test_egress_synthesize_persists_lineage(
    runtime: VoiceRuntime,
) -> None:
    audio = VoiceAudioHandle(
        handle="blob:3",
        audio_format=AudioFormat.OPUS,
        sample_rate_hz=16000,
        duration_ms=1000,
        language="es",
        attributes={"transcript": "hola"},
    )
    await runtime.ingress.transcribe(
        IngressTranscribeRequest(
            audio=audio,
            target_language="es",
            seed="v3",
            correlation_id="conv-3",
        )
    )
    env = await runtime.egress.synthesize(
        EgressSynthesizeRequest(
            text="The team will respond.",
            target_language="es",
            audio_format=AudioFormat.OPUS,
            sample_rate_hz=16000,
            seed="v4",
            correlation_id="conv-3",
        )
    )
    assert env.is_ok
    assert isinstance(env.result, EgressSynthesizeResult)
    assert env.result.identity is not None
    lineage = await runtime.persistence.reconstruct_lineage(
        env.result.identity.correlation_id
    )
    assert lineage is not None
    assert [e.direction for e in lineage.entries] == [
        VoiceDirection.INGRESS,
        VoiceDirection.EGRESS,
    ]


@pytest.mark.asyncio
async def test_egress_rejects_empty_text(
    runtime: VoiceRuntime,
) -> None:
    env = await runtime.egress.synthesize(
        EgressSynthesizeRequest(
            text="",
            target_language="es",
            audio_format=AudioFormat.OPUS,
            sample_rate_hz=16000,
            seed="bad",
        )
    )
    assert env.error is not None


@pytest.mark.asyncio
async def test_voice_replay_verifies_with_recorded_fingerprints(
    runtime: VoiceRuntime,
) -> None:
    audio = VoiceAudioHandle(
        handle="blob:replay",
        audio_format=AudioFormat.OPUS,
        sample_rate_hz=16000,
        duration_ms=1000,
        language="es",
        attributes={"transcript": "hola"},
    )
    env = await runtime.ingress.transcribe(
        IngressTranscribeRequest(
            audio=audio,
            target_language="es",
            seed="vrep",
            correlation_id="conv-r",
        )
    )
    assert isinstance(env.result, IngressTranscribeResult)
    assert env.result.replay is not None
    assert env.result.transcript is not None
    assert verify_voice_replay(
        replay=env.result.replay,
        audio=audio,
        transcript=env.result.transcript.text,
        transcript_language="es",
    )
    # Tamper with audio handle should drift the fingerprint.
    bad_audio = VoiceAudioHandle(
        handle="blob:replay-changed",
        audio_format=AudioFormat.OPUS,
        sample_rate_hz=16000,
        duration_ms=1000,
        language="es",
    )
    assert not verify_voice_replay(
        replay=env.result.replay,
        audio=bad_audio,
        transcript=env.result.transcript.text,
        transcript_language="es",
    )
