"""Spec 1a — conversation session ownership enforcement (#83)."""

from __future__ import annotations

import pytest

from app.services.conversation_service import (
    ConversationAccessDenied,
    ConversationService,
    ConversationServiceError,
)


class _FakeRuntime:
    """Minimal stub for ConversationSessionRuntime."""

    def __init__(self, owner_principal_id: str | None) -> None:
        self._owner = owner_principal_id
        self.submit_calls: list[dict] = []

    async def get_session_owner_principal_id(
        self, *, session_id: str, expected_tenant_id: str
    ) -> str | None:
        return self._owner

    async def submit_message(self, **kwargs) -> object:  # type: ignore[override]
        self.submit_calls.append(kwargs)
        raise ConversationServiceError("test_stub_no_submit")

    async def get_conversation_state(self, **kwargs) -> object:  # type: ignore[override]
        pass


def _service(owner: str | None) -> ConversationService:
    return ConversationService(runtime=_FakeRuntime(owner), redis_client=None)


async def test_owner_principal_can_submit() -> None:
    service = _service("principal-A")
    with pytest.raises(ConversationServiceError) as exc:
        await service.submit_message(
            session_id="s-1",
            tenant_id="t-1",
            content="hello",
            expected_tenant_id="t-1",
            calling_principal_id="principal-A",
        )
    # Should reach the runtime (raising stub error), NOT raise ConversationAccessDenied.
    assert "test_stub_no_submit" in str(exc.value)


async def test_non_owner_principal_is_denied() -> None:
    service = _service("principal-A")
    with pytest.raises(ConversationAccessDenied):
        await service.submit_message(
            session_id="s-1",
            tenant_id="t-1",
            content="hello",
            expected_tenant_id="t-1",
            calling_principal_id="principal-B",
        )


async def test_operator_bypasses_ownership_check() -> None:
    service = _service("principal-A")
    with pytest.raises(ConversationServiceError) as exc:
        await service.submit_message(
            session_id="s-1",
            tenant_id="t-1",
            content="hello",
            expected_tenant_id="t-1",
            calling_principal_id="principal-B",
            is_operator=True,
        )
    assert "test_stub_no_submit" in str(exc.value)


async def test_session_without_owner_passes_through() -> None:
    """Sessions created by webhook ingress have no bound principal."""
    service = _service(None)
    with pytest.raises(ConversationServiceError) as exc:
        await service.submit_message(
            session_id="s-1",
            tenant_id="t-1",
            content="hello",
            expected_tenant_id="t-1",
            calling_principal_id="anyone",
        )
    assert "test_stub_no_submit" in str(exc.value)


async def test_anonymous_caller_denied_on_owned_session() -> None:
    service = _service("principal-A")
    with pytest.raises(ConversationAccessDenied):
        await service.submit_message(
            session_id="s-1",
            tenant_id="t-1",
            content="hello",
            expected_tenant_id="t-1",
            calling_principal_id=None,
        )


async def test_ensure_stream_access_enforces_ownership() -> None:
    service = _service("principal-A")
    with pytest.raises(ConversationAccessDenied):
        await service.ensure_stream_access(
            session_id="s-1",
            expected_tenant_id="t-1",
            calling_principal_id="principal-B",
        )


async def test_ensure_stream_access_operator_bypass() -> None:
    service = _service("principal-A")
    # Operator should not raise ConversationAccessDenied — it calls through to
    # get_conversation_state which returns None from our stub (no error raised).
    await service.ensure_stream_access(
        session_id="s-1",
        expected_tenant_id="t-1",
        calling_principal_id="principal-B",
        is_operator=True,
    )


# ── Router-level (HTTP) wiring tests ─────────────────────────────────────────
# The router must extract principal_id + operator capability from the verified
# authority and thread them into the service, and map ConversationAccessDenied
# to a 403. Service-layer tests alone do not prove this wiring.

import os
from unittest.mock import patch

from starlette.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app
from app.dependencies.authority import OPERATOR_CAPABILITY, require_authority, require_tenant_scope
from app.dependencies.services import get_conversation_service
from app.identity import AuthorityContext
from app.services.conversation_service import ConversationMessageSubmission


class _RecordingService:
    """Records the ownership kwargs the router threads in; optionally denies."""

    def __init__(self, *, deny: bool = False) -> None:
        self.deny = deny
        self.received: dict[str, object] = {}

    async def submit_message(self, **kwargs: object) -> ConversationMessageSubmission:
        self.received = kwargs
        if self.deny:
            raise ConversationAccessDenied("denied")
        return ConversationMessageSubmission(
            turn_id="turn-1", phase_a_response="ok", execution_id="exec-1"
        )


def _conversation_client(*, principal_id: str | None, capabilities: tuple[str, ...], service):
    ctx = AuthorityContext(
        tenant_id="t-1", principal_id=principal_id, capabilities=capabilities
    )
    get_settings.cache_clear()
    try:
        with patch.dict(os.environ, {"ENVIRONMENT": "test", "RATE_LIMIT_ENABLED": "false"}):
            app = create_app()
    finally:
        get_settings.cache_clear()
    app.dependency_overrides[require_tenant_scope] = lambda: "t-1"
    app.dependency_overrides[require_authority] = lambda: ctx
    app.dependency_overrides[get_conversation_service] = lambda: service
    return TestClient(app, raise_server_exceptions=False)


def test_router_threads_principal_id_and_non_operator() -> None:
    service = _RecordingService()
    client = _conversation_client(
        principal_id="principal-A", capabilities=("tenant_read",), service=service
    )
    with client as c:
        resp = c.post("/api/v1/conversation/s-1/message", json={"content": "hi"})
    assert resp.status_code == 200
    assert service.received["calling_principal_id"] == "principal-A"
    assert service.received["is_operator"] is False


def test_router_marks_operator_when_capability_present() -> None:
    service = _RecordingService()
    client = _conversation_client(
        principal_id="op-1", capabilities=(OPERATOR_CAPABILITY,), service=service
    )
    with client as c:
        resp = c.post("/api/v1/conversation/s-1/message", json={"content": "hi"})
    assert resp.status_code == 200
    assert service.received["is_operator"] is True


def test_router_maps_access_denied_to_403() -> None:
    service = _RecordingService(deny=True)
    client = _conversation_client(
        principal_id="principal-B", capabilities=("tenant_read",), service=service
    )
    with client as c:
        resp = c.post("/api/v1/conversation/s-1/message", json={"content": "hi"})
    assert resp.status_code == 403
    # The global problem-details handler flattens the structured detail into a
    # string; assert the code is present in the envelope.
    assert "session_access_denied" in str(resp.json()["detail"])


def test_router_anonymous_principal_threaded_as_none() -> None:
    service = _RecordingService()
    client = _conversation_client(
        principal_id=None, capabilities=("tenant_read",), service=service
    )
    with client as c:
        resp = c.post("/api/v1/conversation/s-1/message", json={"content": "hi"})
    assert resp.status_code == 200
    assert service.received["calling_principal_id"] is None
