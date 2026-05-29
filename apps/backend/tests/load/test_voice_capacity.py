"""PR_RT5 voice capacity admission load tests."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import WebSocketException

from app.api.v1.routers.voice import stream_voice_session
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
        if "DECR" in script:
            self.values[key] = current - 1 if current > 0 else 0
            return self.values[key]
        self.values[key] = max(0, current)
        return self.values[key]


class _AdmissionOnlyWebSocket:
    query_params = {"tenant": "tenant-load"}


class _StopEventWebSocket:
    query_params = {"tenant": "tenant-load"}

    def __init__(self, runtime: object) -> None:
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
                    websocket=_AdmissionOnlyWebSocket(),  # type: ignore[arg-type]
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
    websocket = _StopEventWebSocket(app.state.voice_call_runtime)

    asyncio.run(
        stream_voice_session(
            websocket=websocket,  # type: ignore[arg-type]
            session_id="terminates",
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
                websocket=_AdmissionOnlyWebSocket(),  # type: ignore[arg-type]
                session_id="redis-down",
                capacity=counter,
            )
        )

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


def _current_count(counter: VoiceCapacityCounter) -> int:
    return asyncio.run(counter.current_count())
