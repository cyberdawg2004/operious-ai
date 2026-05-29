"""End-to-end tests for the voice runtime."""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

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
    VoiceConfigurationError,
    VoiceContainmentError,
    VoiceDirection,
    VoiceEgressRuntime,
    VoiceIngressRuntime,
    VoiceRuntime,
    verify_voice_replay,
)
from app.governance.context import GovernanceContext
from app.governance.decisions import PolicyEvaluationResult
from app.governance.enforcement.handlers import (
    AllowHandler,
    DegradeHandler,
    DenyHandler,
    EnforcementHandlerRegistry,
    EscalateHandler,
    RedactHandler,
    RequireApprovalHandler,
)
from app.governance.enforcement.runtime import GovernanceRuntime
from app.governance.enums import Decision, EnforcementStage
from app.governance.evaluators.engine import PolicyEvaluationEngine
from app.governance.persistence.memory import InMemoryGovernanceRepository
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.chain import PolicyChain
from app.governance.subjects.base import SubjectKind


class _AllowCapabilityPolicy(BaseGovernancePolicy):
    name: ClassVar[str] = "voice_runtime_allow_capability"
    supported_stages: ClassVar[frozenset[EnforcementStage]] = (
        frozenset({EnforcementStage.PRE_REQUEST})
    )
    applicable_subject_kinds: ClassVar[frozenset[SubjectKind]] = (
        frozenset({SubjectKind.CAPABILITY})
    )

    async def evaluate(
        self, context: GovernanceContext
    ) -> Sequence[PolicyEvaluationResult]:
        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id="voice_runtime_allowed",
                decision=Decision.ALLOW,
                reason="voice runtime fixture allows capability gate",
            ),
        )


def _handlers() -> EnforcementHandlerRegistry:
    registry = EnforcementHandlerRegistry()
    for handler in (
        AllowHandler(),
        DenyHandler(),
        RedactHandler(),
        DegradeHandler(),
        EscalateHandler(),
        RequireApprovalHandler(),
    ):
        registry.register(handler)
    return registry


def _allowing_governance() -> GovernanceRuntime:
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=_handlers(),
        chains={
            EnforcementStage.PRE_REQUEST: PolicyChain(
                chain_id="voice-runtime-test-capability",
                stage=EnforcementStage.PRE_REQUEST,
                policies=(_AllowCapabilityPolicy(),),
            )
        },
        persistence=InMemoryGovernanceRepository(),
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
            provider=tts,
            persistence=persistence,
            capability_governance=_allowing_governance(),
        ),
    )


def test_voice_egress_requires_governance_at_construction() -> None:
    persistence = InMemoryVoicePersistence()
    tts = DeterministicStubTextToSpeechProvider()

    with pytest.raises(VoiceConfigurationError):
        VoiceEgressRuntime(
            provider=tts,
            persistence=persistence,
            capability_governance=None,
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
