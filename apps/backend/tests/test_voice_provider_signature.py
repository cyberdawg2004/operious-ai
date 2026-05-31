"""Voice provider handshake signature verification (S-04)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from urllib.parse import parse_qsl, urlsplit

import pytest
from fastapi import WebSocketException

from app.api.v1.routers.voice import stream_voice_session
from app.boundary.voice.call import (
    VoiceCallContext,
    VoiceCallSessionRuntime,
    VoiceCallState,
)
from app.boundary.voice.session_token import mint_voice_session_token
from app.core.config import get_settings
from app.core.twilio_signature import (
    TWILIO_CANONICAL_URL_HEADER,
    TWILIO_SIGNATURE_HEADER,
)

_TENANT_ID = "tenant-voice-signature"
_SESSION_ID = "session-provider-sig"
_SESSION_SECRET = "voice-provider-session-secret-32b"
_TWILIO_AUTH_TOKEN = "twilio-provider-auth-token-32b"


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _AcceptingCapacity:
    async def is_available(self) -> bool:
        return True

    async def try_acquire(self) -> bool:
        return True

    async def release(self) -> None:
        return None


class _RuntimeProbe(VoiceCallSessionRuntime):
    def __init__(self) -> None:
        self.started = False
        self.terminated = False
        self._contexts: dict[str, VoiceCallContext] = {}

    async def start_call(
        self,
        *,
        session_id: str,
        tenant_id: str,
        call_nonce: str,
    ) -> VoiceCallContext:
        del call_nonce
        self.started = True
        context = VoiceCallContext(
            call_id=f"call-{session_id}",
            session_id=session_id,
            tenant_id=tenant_id,
            state=VoiceCallState.AWAITING_GREETING,
            turn_count=0,
            current_transcript=None,
            last_activity=datetime.now(UTC),
        )
        self._contexts[context.call_id] = context
        return context

    async def terminate_call(
        self,
        *,
        call_id: str,
        reason: str,
        expected_tenant_id: str,
    ) -> None:
        del reason, expected_tenant_id
        self.terminated = True
        self._contexts.pop(call_id, None)

    def get_context(self, call_id: str) -> VoiceCallContext | None:
        return self._contexts.get(call_id)


def test_valid_token_and_signature_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_voice(monkeypatch=monkeypatch, voice_enabled=True)
    path, headers = _signed_handshake()
    websocket = _HandshakeWebSocket(path=path, headers=headers)

    _run_handshake(websocket)

    runtime = cast(_RuntimeProbe, websocket.app.state.voice_call_runtime)
    assert websocket.accepted is True
    assert websocket.close_codes == [1000]
    assert runtime.started is True
    assert runtime.terminated is True


def test_valid_token_invalid_signature_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_voice(monkeypatch=monkeypatch, voice_enabled=True)
    path, headers = _signed_handshake(auth_token="wrong-auth-token")
    websocket = _HandshakeWebSocket(path=path, headers=headers)

    _assert_rejected(websocket)
    assert websocket.accepted is False
    assert cast(_RuntimeProbe, websocket.app.state.voice_call_runtime).started is False


def test_missing_signature_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_voice(monkeypatch=monkeypatch, voice_enabled=True)
    path, headers = _signed_handshake()
    headers.pop(TWILIO_SIGNATURE_HEADER)
    websocket = _HandshakeWebSocket(path=path, headers=headers)

    _assert_rejected(websocket)
    assert websocket.accepted is False
    assert cast(_RuntimeProbe, websocket.app.state.voice_call_runtime).started is False


def test_signature_cannot_be_disabled_by_param(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_voice(monkeypatch=monkeypatch, voice_enabled=True)
    path, headers = _signed_handshake(
        auth_token="wrong-auth-token",
        extra_query="skip_signature=true",
    )
    websocket = _HandshakeWebSocket(path=path, headers=headers)

    _assert_rejected(websocket)
    assert websocket.accepted is False
    assert cast(_RuntimeProbe, websocket.app.state.voice_call_runtime).started is False


def test_auth_token_never_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "twilio-auth-token-never-log-this-value"
    caplog.set_level(logging.INFO)
    _configure_voice(monkeypatch=monkeypatch, voice_enabled=True)
    path, headers = _signed_handshake(auth_token="wrong-auth-token")
    websocket = _HandshakeWebSocket(
        path=path,
        headers=headers,
        provider_auth_token=secret,
    )

    _assert_rejected(websocket)
    assert secret not in caplog.text


def test_voice_disabled_by_default_rejects_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_voice(monkeypatch=monkeypatch, voice_enabled=False)
    called = False

    async def load_provider_auth_token(tenant_id: str) -> str | None:
        nonlocal called
        del tenant_id
        called = True
        return _TWILIO_AUTH_TOKEN

    path, headers = _signed_handshake()
    websocket = _HandshakeWebSocket(
        path=path,
        headers=headers,
        auth_token_loader=load_provider_auth_token,
    )

    _assert_rejected(websocket)
    assert called is False
    assert websocket.accepted is False
    assert cast(_RuntimeProbe, websocket.app.state.voice_call_runtime).started is False


class _HandshakeWebSocket:
    def __init__(
        self,
        *,
        path: str,
        headers: dict[str, str],
        provider_auth_token: str = _TWILIO_AUTH_TOKEN,
        auth_token_loader: object | None = None,
    ) -> None:
        query = dict(parse_qsl(urlsplit(path).query, keep_blank_values=True))
        self.query_params = query
        self.headers = headers
        self.accepted = False
        self.close_codes: list[int] = []
        self._messages = [json.dumps({"event": "stop"})]
        runtime = _RuntimeProbe()

        async def load_provider_auth_token(tenant_id: str) -> str | None:
            assert tenant_id == _TENANT_ID
            return provider_auth_token

        self.app = SimpleNamespace(
            state=SimpleNamespace(
                voice_call_runtime=runtime,
                voice_provider_auth_token_loader=auth_token_loader
                or load_provider_auth_token,
            )
        )

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        return self._messages.pop(0)

    async def close(self, code: int = 1000) -> None:
        self.close_codes.append(code)


def _configure_voice(
    *,
    monkeypatch: pytest.MonkeyPatch,
    voice_enabled: bool,
) -> None:
    if voice_enabled:
        monkeypatch.setenv("VOICE_ENABLED", "true")
    else:
        monkeypatch.delenv("VOICE_ENABLED", raising=False)
    monkeypatch.setenv("VOICE_SESSION_TOKEN_SECRET", _SESSION_SECRET)
    monkeypatch.setenv("TENANT_CREDENTIAL_MASTER_KEY", "v" * 32)
    get_settings.cache_clear()


def _signed_handshake(
    *,
    session_id: str = _SESSION_ID,
    auth_token: str = _TWILIO_AUTH_TOKEN,
    extra_query: str | None = None,
) -> tuple[str, dict[str, str]]:
    token = mint_voice_session_token(
        secret=_SESSION_SECRET,
        tenant_id=_TENANT_ID,
        session_id=session_id,
        expires_at=int(time.time()) + 300,
    )
    query = f"token={token}"
    if extra_query:
        query = f"{query}&{extra_query}"
    path = f"/api/v1/voice/{session_id}/stream?{query}"
    canonical_url = f"wss://voice.example.test{path}"
    signature = _twilio_signature(auth_token=auth_token, url=canonical_url)
    return (
        path,
        {
            TWILIO_CANONICAL_URL_HEADER: canonical_url,
            TWILIO_SIGNATURE_HEADER: signature,
        },
    )


def _twilio_signature(*, auth_token: str, url: str) -> str:
    return base64.b64encode(
        hmac.new(
            auth_token.encode("utf-8"),
            url.encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("ascii")


def _run_handshake(websocket: _HandshakeWebSocket) -> None:
    asyncio.run(
        stream_voice_session(
            websocket=websocket,  # type: ignore[arg-type]
            session_id=_SESSION_ID,
            capacity=_AcceptingCapacity(),  # type: ignore[arg-type]
        )
    )


def _assert_rejected(websocket: _HandshakeWebSocket) -> None:
    with pytest.raises(WebSocketException) as exc_info:
        _run_handshake(websocket)
    assert exc_info.value.code == 1008
