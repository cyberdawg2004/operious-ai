"""Spec 1b — fixed-window inbound rate-limit primitive."""

from __future__ import annotations

from app.core.rate_limit import FixedWindowLimiter, RateLimitDecision


class _FakeRedis:
    """Hand-rolled async Redis double (repo convention: no fakeredis lib)."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.counts: dict[str, int] = {}
        self.expiry_seconds: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> bool:
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.expiry_seconds[key] = int(seconds)
        return True


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
