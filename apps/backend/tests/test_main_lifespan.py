from __future__ import annotations

import pytest
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.main import _close_pubsub


class _TimeoutPubSub:
    async def aclose(self) -> None:
        raise RedisTimeoutError("Timed out closing connection after 2.0")


class _RuntimeErrorPubSub:
    async def aclose(self) -> None:
        raise RuntimeError("unexpected close failure")


@pytest.mark.asyncio
async def test_close_pubsub_ignores_redis_timeout(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("WARNING", logger="app.main")

    await _close_pubsub(_TimeoutPubSub())

    assert any(
        record.message == "redis_pubsub_close_timeout"
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_close_pubsub_keeps_unexpected_errors_loud() -> None:
    with pytest.raises(RuntimeError, match="unexpected close failure"):
        await _close_pubsub(_RuntimeErrorPubSub())
