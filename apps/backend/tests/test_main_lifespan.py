from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import FastAPI
from redis.exceptions import TimeoutError as RedisTimeoutError

import app.main as main
from app.main import _close_pubsub


class _TimeoutPubSub:
    async def aclose(self) -> None:
        raise RedisTimeoutError("Timed out closing connection after 2.0")


class _RuntimeErrorPubSub:
    async def aclose(self) -> None:
        raise RuntimeError("unexpected close failure")


class _FailingPubSub:
    async def psubscribe(self, _pattern: str) -> None:
        raise RuntimeError("redis unavailable")

    async def aclose(self) -> None:
        return None


class _FailingRedis:
    def pubsub(self) -> _FailingPubSub:
        return _FailingPubSub()


class _SequencedPubSub:
    def __init__(self, *, subscribe_succeeds: bool) -> None:
        self._subscribe_succeeds = subscribe_succeeds

    async def psubscribe(self, _pattern: str) -> None:
        if not self._subscribe_succeeds:
            raise RuntimeError("redis unavailable")

    async def listen(self) -> AsyncIterator[object]:
        raise RuntimeError("listener stream closed")
        yield {}

    async def aclose(self) -> None:
        return None


class _SequencedRedis:
    def __init__(self, outcomes: tuple[bool, ...]) -> None:
        self._outcomes = outcomes
        self.calls = 0

    def pubsub(self) -> _SequencedPubSub:
        outcome = self._outcomes[self.calls]
        self.calls += 1
        return _SequencedPubSub(subscribe_succeeds=outcome)


def _app_with_redis(redis: object) -> FastAPI:
    return cast(FastAPI, SimpleNamespace(state=SimpleNamespace(redis_client=redis)))


def _sleep_recorder(
    delays: list[float],
    *,
    stop_after: int,
) -> Callable[[float], Awaitable[None]]:
    async def _sleep(delay_seconds: float) -> None:
        delays.append(delay_seconds)
        if len(delays) >= stop_after:
            raise asyncio.CancelledError

    return _sleep


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


@pytest.mark.asyncio
async def test_policy_invalidation_listener_backs_off_to_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []
    monkeypatch.setattr(
        main,
        "_sleep_policy_invalidation_retry",
        _sleep_recorder(delays, stop_after=6),
    )

    with pytest.raises(asyncio.CancelledError):
        await main._governance_policy_invalidation_listener(
            _app_with_redis(_FailingRedis())
        )

    assert delays == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0]


@pytest.mark.asyncio
async def test_policy_invalidation_listener_resets_backoff_after_subscribe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []
    redis = _SequencedRedis((False, False, True))
    monkeypatch.setattr(
        main,
        "_sleep_policy_invalidation_retry",
        _sleep_recorder(delays, stop_after=3),
    )

    with pytest.raises(asyncio.CancelledError):
        await main._governance_policy_invalidation_listener(_app_with_redis(redis))

    assert redis.calls == 3
    assert delays == [1.0, 2.0, 1.0]
