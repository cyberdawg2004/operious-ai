from __future__ import annotations

import logging
from types import TracebackType
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.runtime.quota_runtime import TenantQuotaRuntime
from app.cognition.exceptions import ProviderQuotaExceededError


class _FakeRedisPipeline:
    def __init__(self, redis: _FakeRedis) -> None:
        self._redis = redis
        self._commands: list[tuple[str, str, int | None]] = []

    def incr(self, key: str) -> _FakeRedisPipeline:
        self._commands.append(("incr", key, None))
        return self

    def expire(self, key: str, time: int) -> _FakeRedisPipeline:
        self._commands.append(("expire", key, time))
        return self

    async def execute(self) -> list[object]:
        if self._redis.fail:
            raise RuntimeError("redis unavailable")
        results: list[object] = []
        for command, key, seconds in self._commands:
            if command == "incr":
                self._redis.counts[key] = self._redis.counts.get(key, 0) + 1
                results.append(self._redis.counts[key])
            elif command == "expire":
                self._redis.expiry_seconds[key] = int(seconds or 0)
                results.append(True)
        return results


class _FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.counts: dict[str, int] = {}
        self.expiry_seconds: dict[str, int] = {}
        self.pipeline_calls = 0
        self.closed = False

    def pipeline(self) -> _FakeRedisPipeline:
        self.pipeline_calls += 1
        return _FakeRedisPipeline(self)

    async def get(self, key: str) -> object | None:
        if self.fail:
            raise RuntimeError("redis unavailable")
        return self.counts.get(key)

    async def aclose(self) -> None:
        self.closed = True


class _Clock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class _OperatorStore:
    def __init__(self) -> None:
        self.record_ids: set[str] = set()
        self.states: dict[tuple[str, str], str | None] = {}


class _FakeSession:
    def __init__(self, store: _OperatorStore) -> None:
        self._store = store

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = (exc_type, exc, traceback)

    async def scalar(
        self,
        statement: object,
        params: dict[str, Any] | None = None,
    ) -> object | None:
        _ = statement
        payload = params or {}
        if "provider" in payload:
            return self._store.states.get(
                (str(payload["tenant_id"]), str(payload["provider"]))
            )
        record_id = payload.get("record_id")
        if isinstance(record_id, str) and record_id in self._store.record_ids:
            return record_id
        return None

    async def execute(
        self,
        statement: object,
        params: dict[str, Any] | None = None,
    ) -> None:
        _ = statement
        payload = params or {}
        record_id = str(payload["record_id"])
        tenant_id = str(payload["tenant_id"])
        provider = str(payload["provider"])
        circuit_state = payload.get("circuit_state")
        self._store.record_ids.add(record_id)
        self._store.states[(tenant_id, provider)] = (
            circuit_state if circuit_state in ("force_open", "force_close") else None
        )

    async def commit(self) -> None:
        return None


class _FakeSessionFactory:
    def __init__(self) -> None:
        self.store = _OperatorStore()

    def __call__(self) -> _FakeSession:
        return _FakeSession(self.store)


def _runtime(
    session_factory: _FakeSessionFactory,
    *,
    redis: _FakeRedis | None = None,
    clock: _Clock | None = None,
    requests_per_minute: int = 60,
    requests_per_hour: int = 1_000,
) -> TenantQuotaRuntime:
    return TenantQuotaRuntime(
        redis_url="redis://localhost:6379/0",
        session_factory=cast(async_sessionmaker[AsyncSession], session_factory),
        redis_client=redis or _FakeRedis(),
        time_provider=clock,
        request_per_minute_limit=requests_per_minute,
        requests_per_hour_limit=requests_per_hour,
    )


async def _set_operator_override(
    runtime: TenantQuotaRuntime,
    session_factory: _FakeSessionFactory,
    *,
    tenant_id: str,
    provider: str,
    circuit_state: str | None,
) -> None:
    async with session_factory() as session:
        await runtime.set_operator_override(
            tenant_id=tenant_id,
            provider=provider,
            circuit_state=circuit_state,  # pyright: ignore[reportArgumentType]
            set_by="operator:test",
            reason="test override",
            session=cast(AsyncSession, session),
        )
        await session.commit()


@pytest.mark.asyncio
async def test_quota_allows_within_limit() -> None:
    session_factory = _FakeSessionFactory()
    clock = _Clock(120.0)
    runtime = _runtime(
        session_factory,
        clock=clock,
        requests_per_minute=2,
    )

    await runtime.check_and_increment(
        tenant_id="tenant-a",
        provider="anthropic",
        model="claude",
    )

    status = await runtime.get_quota_status(
        tenant_id="tenant-a",
        provider="anthropic",
        model="claude",
    )
    assert status.requests_per_minute_count == 1
    assert status.requests_per_minute_limit == 2
    assert status.redis_available is True


@pytest.mark.asyncio
async def test_quota_raises_when_limit_exceeded() -> None:
    session_factory = _FakeSessionFactory()
    runtime = _runtime(session_factory, requests_per_minute=1)

    await runtime.check_and_increment(
        tenant_id="tenant-a",
        provider="anthropic",
        model="claude",
    )

    with pytest.raises(ProviderQuotaExceededError) as exc_info:
        await runtime.check_and_increment(
            tenant_id="tenant-a",
            provider="anthropic",
            model="claude",
        )
    assert exc_info.value.quota_type == "requests_per_minute"
    assert exc_info.value.retry_after_seconds == 60


@pytest.mark.asyncio
async def test_quota_fails_open_when_redis_unavailable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session_factory = _FakeSessionFactory()
    redis = _FakeRedis(fail=True)
    runtime = _runtime(session_factory, redis=redis, requests_per_minute=0)

    caplog.set_level(logging.WARNING, logger="app.agents.runtime.quota_runtime")
    await runtime.check_and_increment(
        tenant_id="tenant-a",
        provider="anthropic",
        model="claude",
    )

    assert "quota_redis_unavailable" in caplog.text


@pytest.mark.asyncio
async def test_operator_force_open_blocks_request() -> None:
    session_factory = _FakeSessionFactory()
    redis = _FakeRedis()
    runtime = _runtime(session_factory, redis=redis)
    await _set_operator_override(
        runtime,
        session_factory,
        tenant_id="tenant-a",
        provider="anthropic",
        circuit_state="force_open",
    )

    with pytest.raises(ProviderQuotaExceededError) as exc_info:
        await runtime.check_and_increment(
            tenant_id="tenant-a",
            provider="anthropic",
            model="claude",
        )
    assert exc_info.value.quota_type == "operator_override"
    assert redis.pipeline_calls == 0


@pytest.mark.asyncio
async def test_operator_force_close_bypasses_quota() -> None:
    session_factory = _FakeSessionFactory()
    redis = _FakeRedis()
    runtime = _runtime(session_factory, redis=redis, requests_per_minute=0)
    await _set_operator_override(
        runtime,
        session_factory,
        tenant_id="tenant-a",
        provider="anthropic",
        circuit_state="force_close",
    )

    await runtime.check_and_increment(
        tenant_id="tenant-a",
        provider="anthropic",
        model="claude",
    )

    assert redis.pipeline_calls == 0


@pytest.mark.asyncio
async def test_quota_window_resets_after_ttl() -> None:
    session_factory = _FakeSessionFactory()
    clock = _Clock(0.0)
    runtime = _runtime(
        session_factory,
        clock=clock,
        requests_per_minute=1,
    )

    await runtime.check_and_increment(
        tenant_id="tenant-a",
        provider="anthropic",
        model="claude",
    )
    with pytest.raises(ProviderQuotaExceededError):
        await runtime.check_and_increment(
            tenant_id="tenant-a",
            provider="anthropic",
            model="claude",
        )

    clock.value = 60.1
    await runtime.check_and_increment(
        tenant_id="tenant-a",
        provider="anthropic",
        model="claude",
    )


@pytest.mark.asyncio
async def test_quota_is_per_tenant() -> None:
    session_factory = _FakeSessionFactory()
    runtime = _runtime(session_factory, requests_per_minute=1)

    await runtime.check_and_increment(
        tenant_id="tenant-a",
        provider="anthropic",
        model="claude",
    )
    with pytest.raises(ProviderQuotaExceededError):
        await runtime.check_and_increment(
            tenant_id="tenant-a",
            provider="anthropic",
            model="claude",
        )

    await runtime.check_and_increment(
        tenant_id="tenant-b",
        provider="anthropic",
        model="claude",
    )
