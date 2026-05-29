"""PR_RT5 voice capacity admission load tests."""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDisconnect

from app.boundary.voice.call import VOICE_CAPACITY_KEY, VoiceCapacityCounter
from app.governance.enums import Decision
from app.main import create_app
from tests.test_voice_call_runtime import _governance, _runtime

pytestmark = pytest.mark.load


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
        if "DECR" in script and current > 0:
            self.values[key] = current - 1
            return self.values[key]
        self.values[key] = max(0, current)
        return self.values[key]


def test_voice_capacity_admission_blocks_at_limit() -> None:
    limit = 10
    attempts = 15
    app, counter = _app_with_capacity(limit=limit)

    with TestClient(app) as client:
        with ExitStack() as stack:
            for index in range(limit):
                stack.enter_context(
                    client.websocket_connect(_voice_url(f"accepted-{index}"))
                )

            assert _current_count(counter) == limit

            rejected = 0
            for index in range(limit, attempts):
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    with client.websocket_connect(_voice_url(f"rejected-{index}")):
                        pass
                assert exc_info.value.code == 1013
                rejected += 1

            assert rejected == attempts - limit


def test_counter_released_on_call_termination() -> None:
    app, counter = _app_with_capacity(limit=1)

    with TestClient(app) as client:
        with client.websocket_connect(_voice_url("terminates")) as websocket:
            assert _current_count(counter) == 1
            websocket.send_json({"event": "stop"})
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_text()

    _wait_for_count(counter, 0)


def test_admission_fails_closed_when_redis_unavailable() -> None:
    redis = _FakeCapacityRedis(fail_ping=True)
    app, counter = _app_with_capacity(limit=1, redis=redis)

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(_voice_url("redis-down")):
                pass

    assert exc_info.value.code == 1013
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


def _voice_url(seed: str) -> str:
    session_id = uuid.uuid5(uuid.NAMESPACE_URL, f"voice-capacity|{seed}")
    return f"/api/v1/voice/{session_id}/stream?tenant=tenant-load"


def _current_count(counter: VoiceCapacityCounter) -> int:
    return asyncio.run(counter.current_count())


def _wait_for_count(
    counter: VoiceCapacityCounter,
    expected: int,
    *,
    timeout_seconds: float = 1.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _current_count(counter) == expected:
            return
        time.sleep(0.01)
    assert _current_count(counter) == expected
