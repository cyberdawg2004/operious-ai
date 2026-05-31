"""Tenant-scoped provider quota enforcement runtime."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol, cast

from redis.asyncio import from_url  # pyright: ignore[reportUnknownVariableType]
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.cognition.exceptions import ProviderQuotaExceededError

logger = logging.getLogger(__name__)

OperatorCircuitState = Literal["force_open", "force_close"]
_quota_runtime: TenantQuotaRuntime | None = None


class _QuotaRedisPipeline(Protocol):
    def incr(self, key: str) -> _QuotaRedisPipeline: ...

    def incrby(self, key: str, amount: int) -> _QuotaRedisPipeline: ...

    def expire(self, key: str, time: int) -> _QuotaRedisPipeline: ...

    async def execute(self) -> list[object]: ...


class _QuotaRedisClient(Protocol):
    def pipeline(self) -> _QuotaRedisPipeline: ...

    async def get(self, key: str) -> object | None: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class QuotaStatus:
    tenant_id: str
    provider: str
    model: str
    requests_per_minute_count: int
    requests_per_minute_limit: int
    requests_per_hour_count: int
    requests_per_hour_limit: int
    tokens_per_minute_count: int | None
    tokens_per_minute_limit: int
    operator_circuit_state: OperatorCircuitState | None
    redis_available: bool


@dataclass(frozen=True, slots=True)
class _CachedOperatorOverride:
    state: OperatorCircuitState | None
    expires_at: float


@dataclass(frozen=True, slots=True)
class _RedisCount:
    count: int
    available: bool


class TenantQuotaRuntime:
    """Redis sliding-window quota enforcement per tenant/provider/model."""

    _OPERATOR_CACHE_TTL_SECONDS = 30.0

    def __init__(
        self,
        redis_url: str,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        redis_client: _QuotaRedisClient | None = None,
        time_provider: Callable[[], float] | None = None,
        request_per_minute_limit: int = 60,
        tokens_per_minute_limit: int = 100_000,
        requests_per_hour_limit: int = 1_000,
    ) -> None:
        self._redis = redis_client or cast(
            _QuotaRedisClient,
            from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
                health_check_interval=30,
                retry_on_timeout=False,
            ),
        )
        self._owns_redis = redis_client is None
        self._session_factory = session_factory
        self._time = time_provider or time.time
        self._requests_per_minute_limit = request_per_minute_limit
        self._tokens_per_minute_limit = tokens_per_minute_limit
        self._requests_per_hour_limit = requests_per_hour_limit
        self._operator_cache: dict[tuple[str, str], _CachedOperatorOverride] = {}

    async def close(self) -> None:
        """Close the Redis client when this runtime owns it."""

        if self._owns_redis:
            await self._redis.aclose()

    async def check_and_increment(
        self,
        tenant_id: str,
        provider: str,
        model: str,
    ) -> None:
        """
        Check quota and increment counters.

        Redis failures fail open: the request proceeds and only a warning is
        logged. Operator force-open blocks before any Redis increment;
        force-close bypasses quota only, leaving downstream governance intact.
        """

        operator_state = await self._get_operator_override_state(
            tenant_id=tenant_id,
            provider=provider,
        )
        if operator_state == "force_open":
            raise ProviderQuotaExceededError(
                tenant_id=tenant_id,
                provider=provider,
                model=model,
                quota_type="operator_override",
            )
        if operator_state == "force_close":
            return

        now = self._time()

        # Token-per-minute enforcement (S-09). Token usage is recorded
        # post-call via ``record_token_usage``; here we block NEW calls
        # once the current minute window's token budget is exhausted.
        # Read-only check, fails open on Redis error.
        token_count = await self._read_redis_count(
            self._token_minute_key(
                tenant_id=tenant_id,
                provider=provider,
                model=model,
                now=now,
            )
        )
        if token_count.available and token_count.count >= self._tokens_per_minute_limit:
            raise ProviderQuotaExceededError(
                tenant_id=tenant_id,
                provider=provider,
                model=model,
                quota_type="tokens_per_minute",
                retry_after_seconds=60,
            )

        minute_key = self._minute_key(
            tenant_id=tenant_id,
            provider=provider,
            model=model,
            now=now,
        )
        minute_count = await self._check_redis_window(
            minute_key,
            limit=self._requests_per_minute_limit,
            window_seconds=60,
        )
        if minute_count > self._requests_per_minute_limit:
            raise ProviderQuotaExceededError(
                tenant_id=tenant_id,
                provider=provider,
                model=model,
                quota_type="requests_per_minute",
                retry_after_seconds=60,
            )

        hour_key = self._hour_key(
            tenant_id=tenant_id,
            provider=provider,
            model=model,
            now=now,
        )
        hour_count = await self._check_redis_window(
            hour_key,
            limit=self._requests_per_hour_limit,
            window_seconds=3_600,
        )
        if hour_count > self._requests_per_hour_limit:
            raise ProviderQuotaExceededError(
                tenant_id=tenant_id,
                provider=provider,
                model=model,
                quota_type="requests_per_hour",
                retry_after_seconds=3_600,
            )

    async def get_quota_status(
        self,
        tenant_id: str,
        provider: str,
        model: str,
    ) -> QuotaStatus:
        now = self._time()
        minute_count = await self._read_redis_count(
            self._minute_key(
                tenant_id=tenant_id,
                provider=provider,
                model=model,
                now=now,
            )
        )
        hour_count = await self._read_redis_count(
            self._hour_key(
                tenant_id=tenant_id,
                provider=provider,
                model=model,
                now=now,
            )
        )
        token_count = await self._read_redis_count(
            self._token_minute_key(
                tenant_id=tenant_id,
                provider=provider,
                model=model,
                now=now,
            )
        )
        operator_state = await self._get_operator_override_state(
            tenant_id=tenant_id,
            provider=provider,
        )
        return QuotaStatus(
            tenant_id=tenant_id,
            provider=provider,
            model=model,
            requests_per_minute_count=minute_count.count,
            requests_per_minute_limit=self._requests_per_minute_limit,
            requests_per_hour_count=hour_count.count,
            requests_per_hour_limit=self._requests_per_hour_limit,
            tokens_per_minute_count=token_count.count,
            tokens_per_minute_limit=self._tokens_per_minute_limit,
            operator_circuit_state=operator_state,
            redis_available=(
                minute_count.available
                and hour_count.available
                and token_count.available
            ),
        )

    async def record_token_usage(
        self,
        tenant_id: str,
        provider: str,
        model: str,
        tokens: int,
    ) -> None:
        """Record ``tokens`` against the current minute window (S-09).

        Called AFTER an LLM call with the actual total token count.
        Fails open on Redis error (logs a warning) so token accounting
        never blocks a completion that already happened.
        """

        if tokens <= 0:
            return
        key = self._token_minute_key(
            tenant_id=tenant_id,
            provider=provider,
            model=model,
            now=self._time(),
        )
        try:
            pipe = self._redis.pipeline()
            pipe.incrby(key, tokens)
            pipe.expire(key, 60)
            await pipe.execute()
        except Exception as exc:
            logger.warning(
                "quota_redis_unavailable",
                extra={"error": str(exc), "key": key, "tokens": tokens},
            )

    async def set_operator_override(
        self,
        tenant_id: str,
        provider: str,
        circuit_state: OperatorCircuitState | None,
        set_by: str,
        reason: str,
        session: AsyncSession,
    ) -> None:
        if circuit_state not in ("force_open", "force_close", None):
            raise ValueError("circuit_state must be force_open, force_close, or None")

        record_id = self._operator_override_record_id(
            tenant_id=tenant_id,
            provider=provider,
        )
        now = datetime.now(UTC)
        existing_id = await session.scalar(
            text(
                """
                SELECT id
                FROM provider_quota_records
                WHERE id = :record_id
                  AND tenant_id = :tenant_id
                """
            ),
            {
                "record_id": record_id,
                "tenant_id": tenant_id,
            },
        )
        values = {
            "record_id": record_id,
            "tenant_id": tenant_id,
            "provider": provider,
            "model": "*",
            "quota_type": "operator_override",
            "window_start": now,
            "window_count": 0,
            "quota_limit": 0,
            "is_exhausted": False,
            "circuit_state": circuit_state,
            "set_by": set_by,
            "set_at": now,
            "reason": reason,
            "created_at": now,
            "updated_at": now,
            "metadata": "{}",
        }
        if existing_id is None:
            await session.execute(
                text(
                    """
                    INSERT INTO provider_quota_records (
                        id,
                        tenant_id,
                        provider,
                        model,
                        quota_type,
                        window_start,
                        window_count,
                        quota_limit,
                        is_exhausted,
                        operator_circuit_state,
                        operator_set_by,
                        operator_set_at,
                        operator_reason,
                        created_at,
                        updated_at,
                        metadata
                    ) VALUES (
                        :record_id,
                        :tenant_id,
                        :provider,
                        :model,
                        :quota_type,
                        :window_start,
                        :window_count,
                        :quota_limit,
                        :is_exhausted,
                        :circuit_state,
                        :set_by,
                        :set_at,
                        :reason,
                        :created_at,
                        :updated_at,
                        :metadata
                    )
                    """
                ),
                values,
            )
        else:
            await session.execute(
                text(
                    """
                    UPDATE provider_quota_records
                    SET operator_circuit_state = :circuit_state,
                        operator_set_by = :set_by,
                        operator_set_at = :set_at,
                        operator_reason = :reason,
                        updated_at = :updated_at
                    WHERE id = :record_id
                      AND tenant_id = :tenant_id
                    """
                ),
                values,
            )
        self._operator_cache.pop((tenant_id, provider), None)

    async def _check_redis_window(
        self,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> int:
        """
        Returns current count after increment.

        The INCR + EXPIRE pipeline gives a compact fixed-bucket sliding
        window and fails open when Redis is unavailable.
        """

        try:
            pipe = self._redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, window_seconds)
            results = await pipe.execute()
            return self._coerce_redis_int(results[0])
        except Exception as exc:
            logger.warning(
                "quota_redis_unavailable",
                extra={
                    "error": str(exc),
                    "key": key,
                    "limit": limit,
                    "window_seconds": window_seconds,
                },
            )
            return 0

    async def _read_redis_count(self, key: str) -> _RedisCount:
        try:
            value = await self._redis.get(key)
        except Exception as exc:
            logger.warning(
                "quota_redis_unavailable",
                extra={"error": str(exc), "key": key},
            )
            return _RedisCount(count=0, available=False)
        if value is None:
            return _RedisCount(count=0, available=True)
        try:
            return _RedisCount(
                count=self._coerce_redis_int(value),
                available=True,
            )
        except (TypeError, ValueError):
            logger.warning("quota_redis_count_unparseable", extra={"key": key})
            return _RedisCount(count=0, available=True)

    async def _get_operator_override_state(
        self,
        *,
        tenant_id: str,
        provider: str,
    ) -> OperatorCircuitState | None:
        cache_key = (tenant_id, provider)
        cached = self._operator_cache.get(cache_key)
        now = self._time()
        if cached is not None and cached.expires_at > now:
            return cached.state

        state: OperatorCircuitState | None = None
        async with self._session_factory() as session:
            raw_state = await session.scalar(
                text(
                    """
                    SELECT operator_circuit_state
                    FROM provider_quota_records
                    WHERE tenant_id = :tenant_id
                      AND provider = :provider
                      AND quota_type = 'operator_override'
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "provider": provider,
                },
            )

        if raw_state == "force_open" or raw_state == "force_close":
            state = raw_state
        self._operator_cache[cache_key] = _CachedOperatorOverride(
            state=state,
            expires_at=now + self._OPERATOR_CACHE_TTL_SECONDS,
        )
        return state

    @staticmethod
    def _minute_key(
        *,
        tenant_id: str,
        provider: str,
        model: str,
        now: float,
    ) -> str:
        window_bucket = int(now // 60)
        return f"quota:{tenant_id}:{provider}:{model}:{window_bucket}"

    @staticmethod
    def _hour_key(
        *,
        tenant_id: str,
        provider: str,
        model: str,
        now: float,
    ) -> str:
        window_bucket = int(now // 3_600)
        return f"quota:{tenant_id}:{provider}:{model}:hour:{window_bucket}"

    @staticmethod
    def _token_minute_key(
        *,
        tenant_id: str,
        provider: str,
        model: str,
        now: float,
    ) -> str:
        window_bucket = int(now // 60)
        return f"quota:{tenant_id}:{provider}:{model}:tokens:{window_bucket}"

    @staticmethod
    def _operator_override_record_id(*, tenant_id: str, provider: str) -> str:
        return f"provider_quota:{tenant_id}:{provider}:operator_override"

    @staticmethod
    def _coerce_redis_int(value: object) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            return int(value)
        if isinstance(value, bytes):
            return int(value.decode("utf-8"))
        raise TypeError(f"Redis counter is not an integer: {type(value).__name__}")


def initialize_quota_runtime(runtime: TenantQuotaRuntime) -> None:
    global _quota_runtime
    _quota_runtime = runtime


def get_quota_runtime() -> TenantQuotaRuntime | None:
    return _quota_runtime


__all__ = [
    "get_quota_runtime",
    "initialize_quota_runtime",
    "OperatorCircuitState",
    "QuotaStatus",
    "TenantQuotaRuntime",
]
