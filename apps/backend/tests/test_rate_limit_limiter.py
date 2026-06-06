"""Spec 1b — fixed-window inbound rate-limit primitive."""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from typing import Any, cast
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from app.core.rate_limit import FixedWindowLimiter, RateLimitDecision


class _FakeRedis:
    """Hand-rolled async Redis double (repo convention: no fakeredis lib)."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.counts: dict[str, int] = {}
        self.expiry_seconds: dict[str, int] = {}

    async def eval(self, script: str, numkeys: int, *keys_and_args: str) -> int:
        del script, numkeys
        if self.fail:
            raise RuntimeError("redis unavailable")
        key = keys_and_args[0]
        seconds = int(keys_and_args[1])
        self.counts[key] = self.counts.get(key, 0) + 1
        if self.ttl(key) < 0:
            self.expiry_seconds[key] = seconds
        return self.counts[key]

    def ttl(self, key: str) -> int:
        if key not in self.counts:
            return -2
        return self.expiry_seconds.get(key, -1)


@pytest.fixture(scope="module")
def real_redis_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    configured_url = os.environ.get("RATE_LIMIT_TEST_REDIS_URL")
    if configured_url:
        yield configured_url
        return

    host = os.environ.get("REDIS_HOST")
    port = os.environ.get("REDIS_PORT")
    if host and port:
        yield f"redis://{host}:{port}/15"
        return

    redis_server = shutil.which("redis-server")
    if redis_server is None:
        pytest.skip("redis-server unavailable for rate-limit TTL proof")

    server_port = _free_tcp_port()
    data_dir = tmp_path_factory.mktemp("rate-limit-redis")
    process = subprocess.Popen(
        [
            redis_server,
            "--save",
            "",
            "--appendonly",
            "no",
            "--bind",
            "127.0.0.1",
            "--port",
            str(server_port),
            "--dir",
            str(data_dir),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_port("127.0.0.1", server_port, process)
        yield f"redis://127.0.0.1:{server_port}/0"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(host: str, port: int, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                "redis-server exited before accepting connections: "
                f"{process.stderr.read() if process.stderr else ''}"
            )
        try:
            with socket.create_connection((host, port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("redis-server did not start within 5 seconds")


async def test_allows_within_limit() -> None:
    limiter = FixedWindowLimiter(_FakeRedis())
    for _ in range(5):
        decision = await limiter.consume(key="t:1", limit=5, window_seconds=60)
        assert decision.allowed is True
        assert decision.backend_available is True


async def test_blocks_over_limit_with_retry_after() -> None:
    limiter = FixedWindowLimiter(_FakeRedis())
    for _ in range(5):
        await limiter.consume(key="t:2", limit=5, window_seconds=60)
    decision = await limiter.consume(key="t:2", limit=5, window_seconds=60)
    assert decision.allowed is False
    assert decision.retry_after_seconds == 60


async def test_expire_set_only_on_first_increment() -> None:
    redis = _FakeRedis()
    limiter = FixedWindowLimiter(redis)
    await limiter.consume(key="t:3", limit=5, window_seconds=42)
    await limiter.consume(key="t:3", limit=5, window_seconds=99)
    # TTL fixed by the first window, not extended on subsequent hits.
    assert redis.expiry_seconds["t:3"] == 42


async def test_redis_failure_returns_unavailable_decision() -> None:
    limiter = FixedWindowLimiter(_FakeRedis(fail=True))
    decision = await limiter.consume(key="t:4", limit=5, window_seconds=60)
    assert isinstance(decision, RateLimitDecision)
    assert decision.backend_available is False
    assert decision.allowed is False


async def test_fresh_key_gets_real_redis_ttl(real_redis_url: str) -> None:
    redis = _redis_from_url(real_redis_url)
    key = f"rl:test:fresh:{uuid4()}"
    try:
        await redis.delete(key)
        limiter = FixedWindowLimiter(cast(Any, redis))
        decision = await limiter.consume(key=key, limit=5, window_seconds=60)
        assert decision.allowed is True
        assert await redis.ttl(key) > 0
    finally:
        await redis.delete(key)
        await redis.aclose()


async def test_non_expiring_counter_is_repaired_in_real_redis(
    real_redis_url: str,
) -> None:
    redis = _redis_from_url(real_redis_url)
    key = f"rl:test:persisted:{uuid4()}"
    try:
        await redis.set(key, 158)
        await redis.persist(key)
        assert await redis.ttl(key) == -1

        limiter = FixedWindowLimiter(cast(Any, redis))
        decision = await limiter.consume(key=key, limit=1_000, window_seconds=60)

        assert decision.allowed is True
        assert await redis.get(key) == "159"
        assert await redis.ttl(key) > 0
    finally:
        await redis.delete(key)
        await redis.aclose()


async def test_window_expires_and_allows_again_in_real_redis(
    real_redis_url: str,
) -> None:
    redis = _redis_from_url(real_redis_url)
    key = f"rl:test:reset:{uuid4()}"
    try:
        await redis.delete(key)
        limiter = FixedWindowLimiter(cast(Any, redis))
        first = await limiter.consume(key=key, limit=1, window_seconds=1)
        blocked = await limiter.consume(key=key, limit=1, window_seconds=1)
        await asyncio.sleep(1.2)
        reset = await limiter.consume(key=key, limit=1, window_seconds=1)

        assert first.allowed is True
        assert blocked.allowed is False
        assert reset.allowed is True
    finally:
        await redis.delete(key)
        await redis.aclose()


def _redis_from_url(url: str) -> Redis:
    return Redis.from_url(url, decode_responses=True)  # pyright: ignore[reportUnknownMemberType]
