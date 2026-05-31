"""PR_RT4 voice call runtime, turn-taking, and persistence tests."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import ClassVar, FrozenSet

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from starlette.testclient import WebSocketDisconnect

from app.boundary.voice import (
    AudioFormat,
    DeterministicStubSpeechToTextProvider,
    DeterministicStubTextToSpeechProvider,
    IngressTranscribeRequest,
    InMemoryVoicePersistence,
    VoiceAudioHandle,
    VoiceConfigurationError,
    VoiceEgressRuntime,
    VoiceIngressRuntime,
    VoiceRuntime,
)
from app.boundary.voice.adapters.base import (
    TextToSpeechProviderRequest,
    TextToSpeechProviderResponse,
)
from app.boundary.voice.call import (
    BargeinDetector,
    ResponseBudget,
    SilenceDetector,
    VoiceCallSessionRuntime,
    VoiceCallState,
)
from app.boundary.voice.persistence.postgres import (
    PostgresVoicePersistence,
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
from app.governance.subjects.capability import CapabilityGovernanceSubject
from app.main import create_app
from tests.conftest import requires_postgres, set_pg_rls_tenant


class _DecisionPolicy(BaseGovernancePolicy):
    name: ClassVar[str] = "voice_call_decision_policy"
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_REQUEST}
    )
    applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
        {SubjectKind.CAPABILITY}
    )

    def __init__(self, decision: Decision) -> None:
        self._decision = decision

    async def evaluate(
        self, context: GovernanceContext
    ) -> Sequence[PolicyEvaluationResult]:
        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id=f"voice_{self._decision.value}",
                decision=self._decision,
                reason=f"fixture returned {self._decision.value}",
            ),
        )


class _CountingTTSProvider(DeterministicStubTextToSpeechProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def synthesize(
        self, request: TextToSpeechProviderRequest
    ) -> TextToSpeechProviderResponse:
        self.calls += 1
        return await super().synthesize(request)


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


def _governance(
    decision: Decision,
) -> tuple[GovernanceRuntime, InMemoryGovernanceRepository]:
    persistence = InMemoryGovernanceRepository()
    chain = PolicyChain(
        chain_id="voice.call.chain",
        stage=EnforcementStage.PRE_REQUEST,
        policies=(_DecisionPolicy(decision),),
    )
    return (
        GovernanceRuntime(
            engine=PolicyEvaluationEngine(),
            handler_registry=_handlers(),
            chains={EnforcementStage.PRE_REQUEST: chain},
            persistence=persistence,
        ),
        persistence,
    )


async def _persist_decision(
    governance: GovernanceRuntime,
    *,
    tenant_id: str,
) -> uuid.UUID:
    envelope = await governance.evaluate(
        GovernanceContext(
            stage=EnforcementStage.PRE_REQUEST,
            action="boundary.voice.egress",
            resource="voice-call",
            actor="voice-call-test",
            tenant_id=tenant_id,
            subject=CapabilityGovernanceSubject(
                required_capability="boundary.voice.egress",
                held_capabilities=frozenset({"boundary.voice.egress"}),
                tenant_id=tenant_id,
                actor="voice-call-test",
            ),
        )
    )
    assert envelope.decision is not None
    return envelope.decision.decision_id


def _runtime(
    *,
    governance: GovernanceRuntime,
    tts: DeterministicStubTextToSpeechProvider | None = None,
) -> VoiceCallSessionRuntime:
    persistence = InMemoryVoicePersistence()
    voice_runtime = VoiceRuntime(
        ingress=VoiceIngressRuntime(
            provider=DeterministicStubSpeechToTextProvider(),
            persistence=persistence,
        ),
        egress=VoiceEgressRuntime(
            provider=tts or DeterministicStubTextToSpeechProvider(),
            persistence=persistence,
            capability_governance=governance,
        ),
    )
    return VoiceCallSessionRuntime(
        voice_runtime=voice_runtime,
        capability_governance=governance,
    )


def _audio(**attributes: object) -> VoiceAudioHandle:
    return VoiceAudioHandle(
        handle=f"audio:{uuid.uuid5(uuid.NAMESPACE_URL, str(attributes))}",
        audio_format=AudioFormat.PCM_S16LE,
        sample_rate_hz=16000,
        duration_ms=100,
        language="en",
        attributes=attributes,
    )


def test_voice_egress_requires_governance_at_construction() -> None:
    with pytest.raises(VoiceConfigurationError):
        VoiceEgressRuntime(
            provider=DeterministicStubTextToSpeechProvider(),
            persistence=InMemoryVoicePersistence(),
            capability_governance=None,  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_voice_synthesis_requires_allow_decision() -> None:
    deny_governance, _ = _governance(Decision.DENY)
    deny_id = await _persist_decision(
        deny_governance, tenant_id="tenant-voice"
    )
    deny_runtime = _runtime(governance=deny_governance)
    deny_context = await deny_runtime.start_call(
        session_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "session-deny")),
        tenant_id="tenant-voice",
        call_nonce="call-deny",
    )

    with pytest.raises(VoiceConfigurationError):
        await deny_runtime.deliver_response(
            call_id=deny_context.call_id,
            response_text="Denied response",
            governance_decision_id=str(deny_id),
            expected_tenant_id="tenant-voice",
        )

    allow_governance, _ = _governance(Decision.ALLOW)
    allow_id = await _persist_decision(
        allow_governance, tenant_id="tenant-voice"
    )
    allow_runtime = _runtime(governance=allow_governance)
    allow_context = await allow_runtime.start_call(
        session_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "session-allow")),
        tenant_id="tenant-voice",
        call_nonce="call-allow",
    )
    result = await allow_runtime.deliver_response(
        call_id=allow_context.call_id,
        response_text="Allowed response",
        governance_decision_id=str(allow_id),
        expected_tenant_id="tenant-voice",
    )

    assert result.synthesis.audio.handle.startswith("stub-audio:")


def test_silence_detector_triggers_utterance_complete() -> None:
    detector = SilenceDetector()
    now = datetime.now(UTC)

    assert detector.is_utterance_complete(
        now - timedelta(milliseconds=900),
        now,
    )


@pytest.mark.asyncio
async def test_barge_in_detected_during_speaking() -> None:
    detector = BargeinDetector()
    governance, _ = _governance(Decision.ALLOW)
    runtime = _runtime(governance=governance)
    context = await runtime.start_call(
        session_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "session-barge")),
        tenant_id="tenant-voice",
        call_nonce="call-barge",
    )
    runtime._contexts[context.call_id] = context.__class__(
        call_id=context.call_id,
        session_id=context.session_id,
        tenant_id=context.tenant_id,
        state=VoiceCallState.SPEAKING,
        turn_count=context.turn_count,
        current_transcript=context.current_transcript,
        last_activity=context.last_activity,
    )

    assert detector.is_barge_in(
        VoiceCallState.SPEAKING, _audio(transcript="hello")
    )
    updated = await runtime.handle_audio_chunk(
        call_id=context.call_id,
        audio_handle=_audio(transcript="interrupting"),
        expected_tenant_id="tenant-voice",
    )

    assert updated.state is VoiceCallState.LISTENING
    states = [event.to_state for event in runtime.timeline_events(context.call_id)]
    assert VoiceCallState.BARGE_IN in states


@pytest.mark.asyncio
async def test_full_call_with_stubs() -> None:
    governance, _ = _governance(Decision.ALLOW)
    decision_id = await _persist_decision(
        governance, tenant_id="tenant-voice"
    )
    runtime = _runtime(governance=governance)
    session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "session-full-call"))
    context = await runtime.start_call(
        session_id=session_id,
        tenant_id="tenant-voice",
        call_nonce="call-full",
    )
    processed = await runtime.handle_audio_chunk(
        call_id=context.call_id,
        audio_handle=_audio(
            transcript="I need warranty help",
            received_at=datetime.now(UTC) - timedelta(milliseconds=900),
        ),
        expected_tenant_id="tenant-voice",
    )

    assert processed.state is VoiceCallState.PROCESSING
    assert processed.current_transcript == "I need warranty help"

    result = await runtime.deliver_response(
        call_id=context.call_id,
        response_text="I can help with that warranty.",
        governance_decision_id=str(decision_id),
        expected_tenant_id="tenant-voice",
    )

    assert result.synthesis.audio.handle.startswith("stub-audio:")
    assert runtime.get_context(context.call_id).state is VoiceCallState.SPEAKING


@pytest.mark.asyncio
async def test_deliver_response_requires_governance_decision_id() -> None:
    governance, _ = _governance(Decision.ALLOW)
    tts = _CountingTTSProvider()
    runtime = _runtime(governance=governance, tts=tts)
    context = await runtime.start_call(
        session_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "session-no-gov")),
        tenant_id="tenant-voice",
        call_nonce="call-no-gov",
    )

    with pytest.raises(VoiceConfigurationError):
        await runtime.deliver_response(
            call_id=context.call_id,
            response_text="No governance",
            governance_decision_id="",
            expected_tenant_id="tenant-voice",
        )

    assert tts.calls == 0


@pytest.mark.asyncio
async def test_terminated_call_removed_from_contexts() -> None:
    governance, _ = _governance(Decision.ALLOW)
    runtime = _runtime(governance=governance)
    context = await runtime.start_call(
        session_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "session-terminated")),
        tenant_id="tenant-voice",
        call_nonce="call-terminated",
    )

    assert runtime.get_context(context.call_id) is not None
    assert runtime.active_call_count() == 1

    await runtime.terminate_call(
        call_id=context.call_id,
        reason="test_complete",
        expected_tenant_id="tenant-voice",
    )

    assert runtime.get_context(context.call_id) is None
    assert runtime.active_call_count() == 0


@requires_postgres
@pytest.mark.asyncio
async def test_postgres_voice_persistence_tenant_isolation(pg_session) -> None:
    persistence = PostgresVoicePersistence(pg_session)
    governance, _ = _governance(Decision.ALLOW)
    runtime = _runtime(governance=governance)
    context = await runtime.start_call(
        session_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "session-pg")),
        tenant_id="tenant-a",
        call_nonce="call-pg",
    )
    envelope = await runtime._voice_runtime.ingress.transcribe(
        request=IngressTranscribeRequest(
            audio=_audio(
                transcript="tenant scoped",
                session_id=context.session_id,
            ),
            target_language="en",
            seed="tenant-a-ingress",
            correlation_id=context.call_id,
            tenant_id="tenant-a",
            attributes={"session_id": context.session_id},
        )
    )
    assert envelope.result is not None
    stored = await runtime._voice_runtime.persistence.get_ingress(
        envelope.result.identity.event_id
    )
    assert stored is not None
    await persistence.write_ingress(stored)

    await set_pg_rls_tenant(pg_session, "tenant-a")
    visible = await persistence.get_ingress(envelope.result.identity.event_id)
    assert visible is not None

    try:
        await pg_session.execute(text("SET LOCAL ROLE operious_app_test"))
        await set_pg_rls_tenant(pg_session, "tenant-b")
        hidden = await persistence.get_ingress(envelope.result.identity.event_id)
    finally:
        await pg_session.execute(text("RESET ROLE"))
    assert hidden is None


def test_websocket_endpoint_rejects_unauthenticated() -> None:
    app = create_app()
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/api/v1/voice/session-1/stream"):
            pass

    assert exc_info.value.code == 1008


def test_response_budget_filler_is_deterministic() -> None:
    budget = ResponseBudget()
    context = {"session_id": "session-123"}

    assert budget.select_filler(context) == budget.select_filler(context)
