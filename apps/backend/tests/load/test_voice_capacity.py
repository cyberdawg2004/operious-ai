"""PR_RT5 voice capacity admission load tests."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import WebSocketException

from app.api.v1.routers.voice import stream_voice_session
from app.boundary.voice.call import VOICE_CAPACITY_KEY, VoiceCapacityCounter
from app.boundary.voice.session_token import mint_voice_session_token
from app.core.config import get_settings
from app.governance.enums import Decision
from app.main import create_app
from tests.test_voice_call_runtime import _governance, _runtime

pytestmark = pytest.mark.load

_VOICE_SECRET = "voice-load-test-secret-material-32-bytes-x"


def _voice_token(session_id: str) -> str:
    return mint_voice_session_token(
        secret=_VOICE_SECRET,
        tenant_id="tenant-load",
        session_id=session_id,
        expires_at=2_000_000_000,
    )


@pytest.fixture(autouse=True)
def _enable_voice(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VOICE_ENABLED", "true")
    monkeypatch.setenv("VOICE_SESSION_TOKEN_SECRET", _VOICE_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _FakeCapacityRedis:
    def __init__(self, *, fail_ping: bool = False) -> None:
        self.values: dict[str, int] = {}
        self.fail_ping = fail_ping

    async def ping(self) -> bool:
        if self.fail_ping:
            raise ConnectionError("redis unavailable")
        return True

    async def get(self, name: str) -> int | None:
        return self.values.get(name)

    async def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: object,
    ) -> int:
        del numkeys
        key = str(keys_and_args[0])
        current = self.values.get(key, 0)
        if "INCR" in script:
            limit = int(keys_and_args[1])
            if current < limit:
                self.values[key] = current + 1
                return 1
            return 0
        if "DECR" in script:
            self.values[key] = current - 1 if current > 0 else 0
            return self.values[key]
        self.values[key] = max(0, current)
        return self.values[key]


class _AdmissionOnlyWebSocket:
    def __init__(self, session_id: str) -> None:
        self.query_params = {"token": _voice_token(session_id)}


class _TenantOnlyWebSocket:
    query_params = {"tenant": "tenant-load"}


class _StopEventWebSocket:
    def __init__(self, runtime: object, session_id: str) -> None:
        self.query_params = {"token": _voice_token(session_id)}
        self.app = SimpleNamespace(
            state=SimpleNamespace(voice_call_runtime=runtime)
        )
        self.accepted = False
        self.closed = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        return json.dumps({"event": "stop"})

    async def close(self) -> None:
        self.closed = True


class _OversizedFrameWebSocket:
    """Sends a single media frame larger than VOICE_MAX_FRAME_BYTES."""

    def __init__(self, runtime: object, session_id: str = "oversized") -> None:
        self.query_params = {"token": _voice_token(session_id)}
        self.app = SimpleNamespace(
            state=SimpleNamespace(voice_call_runtime=runtime)
        )
        self.accepted = False
        self.close_code: int | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        return json.dumps(
            {"event": "media", "media": {"payload": "A" * 70_000}}
        )

    async def close(self, code: int = 1000) -> None:
        self.close_code = code

    async def send_json(self, data: object) -> None:
        del data


def test_voice_capacity_admission_blocks_at_limit() -> None:
    limit = 10
    attempts = 15
    _, counter = _app_with_capacity(limit=limit)
    accepted = 0

    for _ in range(limit):
        assert asyncio.run(counter.try_acquire()) is True
        accepted += 1

    assert _current_count(counter) == limit

    rejected = 0
    for index in range(limit, attempts):
        with pytest.raises(WebSocketException) as exc_info:
            asyncio.run(
                stream_voice_session(
                    websocket=_AdmissionOnlyWebSocket(
                        session_id=f"rejected-{index}",
                    ),  # type: ignore[arg-type]
                    session_id=f"rejected-{index}",
                    capacity=counter,
                )
            )
        assert exc_info.value.code == 1013
        rejected += 1

    for _ in range(limit):
        asyncio.run(counter.release())

    assert accepted == limit
    assert rejected == attempts - limit
    assert _current_count(counter) == 0


def test_counter_released_on_call_termination() -> None:
    app, counter = _app_with_capacity(limit=1)
    session_id = "terminates"
    websocket = _StopEventWebSocket(app.state.voice_call_runtime, session_id)

    asyncio.run(
        stream_voice_session(
            websocket=websocket,  # type: ignore[arg-type]
            session_id=session_id,
            capacity=counter,
        )
    )

    assert websocket.accepted is True
    assert websocket.closed is True
    assert _current_count(counter) == 0


def test_admission_fails_closed_when_redis_unavailable() -> None:
    redis = _FakeCapacityRedis(fail_ping=True)
    _, counter = _app_with_capacity(limit=1, redis=redis)

    with pytest.raises(WebSocketException) as exc_info:
        asyncio.run(
            stream_voice_session(
                websocket=_AdmissionOnlyWebSocket(
                    session_id="redis-down",
                ),  # type: ignore[arg-type]
                session_id="redis-down",
                capacity=counter,
            )
        )

    assert exc_info.value.code == 1013
    assert _current_count(counter) == 0


def test_oversized_frame_closes_call_and_releases_capacity() -> None:
    app, counter = _app_with_capacity(limit=1)
    websocket = _OversizedFrameWebSocket(app.state.voice_call_runtime)

    asyncio.run(
        stream_voice_session(
            websocket=websocket,  # type: ignore[arg-type]
            session_id="oversized",
            capacity=counter,
        )
    )

    assert websocket.accepted is True
    assert websocket.close_code == 1009  # WS_1009_MESSAGE_TOO_BIG
    assert _current_count(counter) == 0


def test_query_tenant_without_signed_token_is_rejected() -> None:
    _, counter = _app_with_capacity(limit=1)

    with pytest.raises(WebSocketException) as exc_info:
        asyncio.run(
            stream_voice_session(
                websocket=_TenantOnlyWebSocket(),  # type: ignore[arg-type]
                session_id="tenant-query-only",
                capacity=counter,
            )
        )

    assert exc_info.value.code == 1008
    assert _current_count(counter) == 0


def test_counter_floor_at_zero() -> None:
    counter = VoiceCapacityCounter(_FakeCapacityRedis(), limit=1)

    asyncio.run(counter.release())
    asyncio.run(counter.release())

    assert _current_count(counter) == 0


def _app_with_capacity(
    *,
    limit: int,
    redis: _FakeCapacityRedis | None = None,
) -> tuple[object, VoiceCapacityCounter]:
    governance, _ = _governance(Decision.ALLOW)
    app = create_app()
    counter = VoiceCapacityCounter(
        redis_client=redis or _FakeCapacityRedis(),
        limit=limit,
        key=VOICE_CAPACITY_KEY,
    )
    app.state.voice_capacity_counter = counter
    app.state.voice_call_runtime = _runtime(governance=governance)
    return app, counter


def _current_count(counter: VoiceCapacityCounter) -> int:
    return asyncio.run(counter.current_count())
