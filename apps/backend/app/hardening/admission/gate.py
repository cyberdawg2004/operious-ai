"""AdmissionGate evaluates queue pressure without owning persistence."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from inspect import isawaitable
from typing import Any, Protocol

from app.hardening.admission.models import (
    AdmissionDecision,
    AdmissionOutcome,
    AdmissionReason,
)

logger = logging.getLogger(__name__)

QUEUE_AGE_ZSET_KEY = "queue:age:{queue_name}"


class AdmissionRedisClient(Protocol):
    """Redis subset used by admission checks and queue-age sentinels."""

    def info(self, section: str | None = None) -> Awaitable[Mapping[str, Any]] | Mapping[str, Any]:
        ...

    def llen(self, name: str) -> Awaitable[int] | int:
        ...

    def zrange(
        self,
        name: str,
        start: int,
        end: int,
        *,
        withscores: bool = False,
    ) -> Awaitable[Sequence[Any]] | Sequence[Any]:
        ...


@dataclass(frozen=True, slots=True)
class AdmissionGateThresholds:
    """Environment-backed pressure thresholds for AdmissionGate."""

    queue_depth_warn: int = 500
    queue_depth_reject: int = 2000
    queue_age_warn_seconds: int = 120
    queue_age_reject_seconds: int = 600
    redis_memory_pct_warn: float = 70.0
    redis_memory_pct_reject: float = 90.0
    db_pool_wait_warn_ms: float = 250.0
    db_pool_wait_reject_ms: float = 1000.0


class AdmissionGate:
    """Stateless evaluator for inbound queue admission."""

    def __init__(
        self,
        *,
        redis_client: AdmissionRedisClient,
        thresholds: AdmissionGateThresholds,
    ) -> None:
        self._redis = redis_client
        self._thresholds = thresholds

    async def evaluate(
        self,
        *,
        queue_name: str,
        tenant_id: str | None = None,
        channel: str | None = None,
        db_pool_wait_ms: float | None = None,
    ) -> AdmissionDecision:
        now = datetime.now(timezone.utc)
        decision_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            "|".join(
                (
                    "operious-admission",
                    queue_name,
                    tenant_id or "",
                    channel or "",
                    str(time.time_ns()),
                )
            ),
        )
        redis_memory_pct = await self._redis_memory_pct(queue_name=queue_name)
        queue_depth = await self._queue_depth(queue_name=queue_name)
        queue_age_seconds = await self._queue_age_seconds(queue_name=queue_name)

        if (
            redis_memory_pct is not None
            and redis_memory_pct >= self._thresholds.redis_memory_pct_reject
        ):
            return self._decision(
                decision_id=decision_id,
                outcome=AdmissionOutcome.REJECT,
                reason=AdmissionReason.REDIS_MEMORY_PRESSURE,
                queue_name=queue_name,
                queue_depth=queue_depth,
                queue_age_seconds=queue_age_seconds,
                redis_memory_pct=redis_memory_pct,
                db_pool_wait_ms=db_pool_wait_ms,
                retry_after_seconds=60,
                evaluated_at=now,
            )

        if (
            db_pool_wait_ms is not None
            and db_pool_wait_ms >= self._thresholds.db_pool_wait_reject_ms
        ):
            return self._decision(
                decision_id=decision_id,
                outcome=AdmissionOutcome.REJECT,
                reason=AdmissionReason.DB_POOL_PRESSURE,
                queue_name=queue_name,
                queue_depth=queue_depth,
                queue_age_seconds=queue_age_seconds,
                redis_memory_pct=redis_memory_pct,
                db_pool_wait_ms=db_pool_wait_ms,
                retry_after_seconds=60,
                evaluated_at=now,
            )
        if (
            db_pool_wait_ms is not None
            and db_pool_wait_ms >= self._thresholds.db_pool_wait_warn_ms
        ):
            return self._decision(
                decision_id=decision_id,
                outcome=AdmissionOutcome.DEFER,
                reason=AdmissionReason.DB_POOL_PRESSURE,
                queue_name=queue_name,
                queue_depth=queue_depth,
                queue_age_seconds=queue_age_seconds,
                redis_memory_pct=redis_memory_pct,
                db_pool_wait_ms=db_pool_wait_ms,
                retry_after_seconds=30,
                evaluated_at=now,
            )

        if queue_depth >= self._thresholds.queue_depth_reject:
            return self._decision(
                decision_id=decision_id,
                outcome=AdmissionOutcome.REJECT,
                reason=AdmissionReason.QUEUE_DEPTH_EXCEEDED,
                queue_name=queue_name,
                queue_depth=queue_depth,
                queue_age_seconds=queue_age_seconds,
                redis_memory_pct=redis_memory_pct,
                db_pool_wait_ms=db_pool_wait_ms,
                retry_after_seconds=30,
                evaluated_at=now,
            )
        if queue_depth >= self._thresholds.queue_depth_warn:
            return self._decision(
                decision_id=decision_id,
                outcome=AdmissionOutcome.DEFER,
                reason=AdmissionReason.QUEUE_DEPTH_EXCEEDED,
                queue_name=queue_name,
                queue_depth=queue_depth,
                queue_age_seconds=queue_age_seconds,
                redis_memory_pct=redis_memory_pct,
                db_pool_wait_ms=db_pool_wait_ms,
                retry_after_seconds=15,
                evaluated_at=now,
            )

        if (
            queue_age_seconds is not None
            and queue_age_seconds >= self._thresholds.queue_age_reject_seconds
        ):
            return self._decision(
                decision_id=decision_id,
                outcome=AdmissionOutcome.REJECT,
                reason=AdmissionReason.QUEUE_AGE_EXCEEDED,
                queue_name=queue_name,
                queue_depth=queue_depth,
                queue_age_seconds=queue_age_seconds,
                redis_memory_pct=redis_memory_pct,
                db_pool_wait_ms=db_pool_wait_ms,
                retry_after_seconds=60,
                evaluated_at=now,
            )
        if (
            queue_age_seconds is not None
            and queue_age_seconds >= self._thresholds.queue_age_warn_seconds
        ):
            return self._decision(
                decision_id=decision_id,
                outcome=AdmissionOutcome.DEFER,
                reason=AdmissionReason.QUEUE_AGE_EXCEEDED,
                queue_name=queue_name,
                queue_depth=queue_depth,
                queue_age_seconds=queue_age_seconds,
                redis_memory_pct=redis_memory_pct,
                db_pool_wait_ms=db_pool_wait_ms,
                retry_after_seconds=20,
                evaluated_at=now,
            )

        return self._decision(
            decision_id=decision_id,
            outcome=AdmissionOutcome.ADMIT,
            reason=None,
            queue_name=queue_name,
            queue_depth=queue_depth,
            queue_age_seconds=queue_age_seconds,
            redis_memory_pct=redis_memory_pct,
            db_pool_wait_ms=db_pool_wait_ms,
            retry_after_seconds=30,
            evaluated_at=now,
        )

    async def redis_memory_pct(self) -> float | None:
        """Return Redis memory pressure, or None when unbounded/unavailable."""

        return await self._redis_memory_pct(queue_name=None)

    async def queue_age_seconds(self, *, queue_name: str) -> float | None:
        """Return oldest message age for a queue, if the sentinel exists."""

        return await self._queue_age_seconds(queue_name=queue_name)

    async def _redis_memory_pct(self, *, queue_name: str | None) -> float | None:
        try:
            info = await _resolve(self._redis.info("memory"))
            used = int(info.get("used_memory", 0))
            max_memory = int(info.get("maxmemory", 0))
            if max_memory <= 0:
                return None
            return round((used / max_memory) * 100, 2)
        except Exception:  # noqa: BLE001 - admission must fail open here.
            logger.warning(
                "admission_redis_memory_check_failed",
                extra={"queue_name": queue_name},
            )
            return None

    async def _queue_depth(self, *, queue_name: str) -> int:
        try:
            value = await _resolve(self._redis.llen(queue_name))
            return int(value or 0)
        except Exception:  # noqa: BLE001 - admission must fail open here.
            logger.warning(
                "admission_queue_depth_check_failed",
                extra={"queue_name": queue_name},
            )
            return 0

    async def _queue_age_seconds(self, *, queue_name: str) -> float | None:
        try:
            key = QUEUE_AGE_ZSET_KEY.format(queue_name=queue_name)
            result = await _resolve(
                self._redis.zrange(key, 0, 0, withscores=True)
            )
            if not result:
                return None
            first = result[0]
            if not isinstance(first, tuple) or len(first) < 2:
                return None
            return round(max(0.0, time.time() - float(first[1])), 2)
        except Exception:  # noqa: BLE001 - admission must fail open here.
            logger.warning(
                "admission_queue_age_check_failed",
                extra={"queue_name": queue_name},
            )
            return None

    @staticmethod
    def _decision(
        *,
        decision_id: uuid.UUID,
        outcome: AdmissionOutcome,
        reason: AdmissionReason | None,
        queue_name: str,
        queue_depth: int,
        queue_age_seconds: float | None,
        redis_memory_pct: float | None,
        db_pool_wait_ms: float | None,
        retry_after_seconds: int,
        evaluated_at: datetime,
    ) -> AdmissionDecision:
        return AdmissionDecision(
            decision_id=decision_id,
            outcome=outcome,
            reason=reason,
            queue_name=queue_name,
            queue_depth=queue_depth,
            queue_age_seconds=queue_age_seconds,
            redis_memory_pct=redis_memory_pct,
            db_pool_wait_ms=db_pool_wait_ms,
            retry_after_seconds=retry_after_seconds,
            evaluated_at=evaluated_at,
        )


async def _resolve(value: Awaitable[Any] | Any) -> Any:
    if isawaitable(value):
        return await value
    return value


__all__ = [
    "AdmissionGate",
    "AdmissionGateThresholds",
    "AdmissionRedisClient",
    "QUEUE_AGE_ZSET_KEY",
]
