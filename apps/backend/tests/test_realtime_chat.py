from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.session import (
    InMemorySessionPersistence,
    OpenSessionRequest,
    OpenSessionResult,
    SessionEventKind,
    SessionEventQuery,
    SessionLifecyclePhase,
    SessionRuntime,
    SessionScope,
)
from app.session.conversation import (
    ConversationExecutionIntent,
    ConversationSessionRuntime,
    phase_a_templates,
    publish_conversation_event,
    subscribe_conversation_events,
)
from app.session.identity import SessionId

TENANT_ID = "tenant-realtime-chat"


@dataclass(slots=True)
class _FakeDiagnosticRequester:
    calls: list[dict[str, str]] = field(default_factory=list)

    async def request_diagnostic_execution(
        self,
        *,
        session_id: str,
        tenant_id: str,
        turn_id: str,
        customer_message: str,
        source_language: str,
        conversation_history: tuple[Mapping[str, Any], ...],
        expected_tenant_id: str,
    ) -> ConversationExecutionIntent:
        self.calls.append(
            {
                "session_id": session_id,
                "tenant_id": tenant_id,
                "turn_id": turn_id,
                "customer_message": customer_message,
                "source_language": source_language,
                "conversation_history_size": str(len(conversation_history)),
                "expected_tenant_id": expected_tenant_id,
            }
        )
        return ConversationExecutionIntent(
            dispatch_id="dispatch-chat",
            execution_id="execution-chat",
            governance_decision_id="decision-chat",
        )


@dataclass(slots=True)
class _FakePublisher:
    events: list[Mapping[str, Any]] = field(default_factory=list)

    async def publish(
        self,
        *,
        session_id: str,
        event: Mapping[str, Any],
    ) -> None:
        self.events.append({"session_id": session_id, **dict(event)})


class _RaisingRedis:
    async def publish(self, channel: str, payload: str) -> None:
        del channel, payload
        raise RuntimeError("redis unavailable")


class _FakeRedis:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, payload: str) -> None:
        self.published.append((channel, payload))
        self.messages.append({"type": "message", "data": payload})

    def pubsub(self) -> "_FakePubSub":
        return _FakePubSub(self.messages)


class _FakePubSub:
    def __init__(self, messages: list[dict[str, object]]) -> None:
        self._messages = messages

    async def subscribe(self, channel: str) -> None:
        self.channel = channel

    async def get_message(
        self,
        *,
        ignore_subscribe_messages: bool,
        timeout: float,
    ) -> dict[str, object] | None:
        del ignore_subscribe_messages, timeout
        if self._messages:
            return self._messages.pop(0)
        return None

    async def unsubscribe(self, channel: str) -> None:
        self.channel = channel

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_conversation_submit_message_returns_phase_a() -> None:
    store = InMemorySessionPersistence()
    session_id = await _open_session(store)
    requester = _FakeDiagnosticRequester()
    publisher = _FakePublisher()
    runtime = ConversationSessionRuntime(
        session_repository=store,
        diagnostic_requester=requester,
        event_publisher=publisher,
    )

    result = await runtime.submit_message(
        session_id=session_id,
        tenant_id=TENANT_ID,
        customer_message="My charger stopped charging",
        expected_tenant_id=TENANT_ID,
    )

    assert result.phase_a_turn.content in phase_a_templates()
    assert result.execution.execution_id == "execution-chat"
    assert requester.calls[0]["customer_message"] == "My charger stopped charging"
    assert requester.calls[0]["source_language"] == "en"
    assert requester.calls[0]["conversation_history_size"] == "2"
    page = await store.list_events(
        SessionEventQuery(session_id=SessionId(uuid.UUID(session_id))),
        expected_tenant_id=TENANT_ID,
    )
    kinds = [event.kind for event in page.events]
    assert SessionEventKind.CUSTOMER_MESSAGE in kinds
    assert SessionEventKind.ASSISTANT_RESPONSE in kinds
    assert any(event.get("phase") == "processing" for event in publisher.events)


@pytest.mark.asyncio
async def test_phase_a_content_is_not_llm_generated(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_llm_call() -> None:
        raise AssertionError("Phase A must not call an LLM provider")

    monkeypatch.setattr(
        "app.workers.agent_tasks._diagnostic_llm_client",
        fail_llm_call,
    )
    store = InMemorySessionPersistence()
    session_id = await _open_session(store)
    runtime = ConversationSessionRuntime(
        session_repository=store,
        diagnostic_requester=_FakeDiagnosticRequester(),
    )

    result = await runtime.submit_message(
        session_id=session_id,
        tenant_id=TENANT_ID,
        customer_message="Can I get a refund?",
        expected_tenant_id=TENANT_ID,
    )

    assert result.phase_a_turn.content in phase_a_templates()


@pytest.mark.asyncio
async def test_stream_receives_phase_b_after_pipeline() -> None:
    redis = _FakeRedis()
    phase_b = {
        "type": "turn",
        "role": "assistant",
        "phase": "B",
        "tenant_id": TENANT_ID,
        "session_id": "session-chat",
        "turn_id": "turn-b",
        "content": "Governed response",
        "governance_decision_id": "decision-allow",
        "execution_id": "execution-chat",
    }
    await publish_conversation_event(
        redis_client=redis,
        session_id="session-chat",
        event=phase_b,
    )
    await publish_conversation_event(
        redis_client=redis,
        session_id="session-chat",
        event={
            "type": "status",
            "phase": "complete",
            "tenant_id": TENANT_ID,
            "session_id": "session-chat",
        },
    )

    events = [
        event
        async for event in subscribe_conversation_events(
            redis_client=redis,
            session_id="session-chat",
            expected_tenant_id=TENANT_ID,
            timeout_seconds=1,
        )
    ]

    assert events[0]["phase"] == "B"
    assert events[0]["governance_decision_id"] == "decision-allow"
    assert events[0]["content"] == "Governed response"


@pytest.mark.asyncio
async def test_stream_tenant_isolation() -> None:
    redis = _FakeRedis()
    for tenant_id, content in (
        ("tenant-b", "wrong tenant"),
        (TENANT_ID, "right tenant"),
    ):
        await publish_conversation_event(
            redis_client=redis,
            session_id="shared-format-session",
            event={
                "type": "turn",
                "role": "assistant",
                "phase": "B",
                "tenant_id": tenant_id,
                "session_id": "shared-format-session",
                "turn_id": tenant_id,
                "content": content,
            },
        )
    await publish_conversation_event(
        redis_client=redis,
        session_id="shared-format-session",
        event={
            "type": "status",
            "phase": "complete",
            "tenant_id": TENANT_ID,
            "session_id": "shared-format-session",
        },
    )

    events = [
        event
        async for event in subscribe_conversation_events(
            redis_client=redis,
            session_id="shared-format-session",
            expected_tenant_id=TENANT_ID,
            timeout_seconds=1,
        )
    ]

    assert all(event["tenant_id"] == TENANT_ID for event in events)
    assert json.dumps(events)
    assert "wrong tenant" not in json.dumps(events)


@pytest.mark.asyncio
async def test_publish_failure_does_not_fail_task() -> None:
    await publish_conversation_event(
        redis_client=_RaisingRedis(),
        session_id="session-chat",
        event={"type": "status", "phase": "complete", "tenant_id": TENANT_ID},
    )


@pytest.mark.asyncio
async def test_session_transitions_to_active() -> None:
    store = InMemorySessionPersistence()
    session_id = await _open_session(store)
    runtime = ConversationSessionRuntime(
        session_repository=store,
        diagnostic_requester=_FakeDiagnosticRequester(),
    )

    await runtime.submit_message(
        session_id=session_id,
        tenant_id=TENANT_ID,
        customer_message="Hello",
        expected_tenant_id=TENANT_ID,
    )

    record = await store.get_session(
        SessionId(uuid.UUID(session_id)),
        expected_tenant_id=TENANT_ID,
    )
    assert record is not None
    assert record.lifecycle_phase is SessionLifecyclePhase.ACTIVE


async def _open_session(store: InMemorySessionPersistence) -> str:
    session_id = SessionId(uuid.uuid4())
    envelope = await SessionRuntime(persistence=store).open_session(
        OpenSessionRequest(
            scope=SessionScope.TENANT,
            external_handle=str(session_id),
            tenant_id=TENANT_ID,
            session_id_override=session_id,
        )
    )
    assert envelope.is_ok, envelope.trace.error
    assert isinstance(envelope.result, OpenSessionResult)
    assert envelope.result.session is not None
    return str(envelope.result.session.identity.session_id)
