"""Admission-control infrastructure helpers."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Mapping
from inspect import isawaitable
from typing import Any, Protocol

from app.core.config import Settings
from app.hardening.admission import AdmissionGateThresholds
from app.hardening.admission.gate import QUEUE_AGE_ZSET_KEY

logger = logging.getLogger(__name__)


class QueueAgeSentinelClient(Protocol):
    def zadd(
        self,
        name: str,
        mapping: Mapping[str, float],
        *,
        nx: bool = False,
    ) -> Awaitable[int] | int:
        ...

    def zrem(self, name: str, *values: str) -> Awaitable[int] | int:
        ...


class EmptyQueueAgeSentinelCleanupClient(Protocol):
    def zremrangebyscore(
        self,
        name: str,
        min: float | str,
        max: float | str,
    ) -> Awaitable[int] | int:
        ...


def admission_thresholds_from_settings(
    settings: Settings,
) -> AdmissionGateThresholds:
    return AdmissionGateThresholds(
        queue_depth_warn=settings.ADMISSION_QUEUE_DEPTH_WARN,
        queue_depth_reject=settings.ADMISSION_QUEUE_DEPTH_REJECT,
        queue_age_warn_seconds=settings.ADMISSION_QUEUE_AGE_WARN_SECONDS,
        queue_age_reject_seconds=settings.ADMISSION_QUEUE_AGE_REJECT_SECONDS,
        redis_memory_pct_warn=settings.ADMISSION_REDIS_MEMORY_PCT_WARN,
        redis_memory_pct_reject=settings.ADMISSION_REDIS_MEMORY_PCT_REJECT,
        db_pool_wait_warn_ms=settings.ADMISSION_DB_POOL_WAIT_WARN_MS,
        db_pool_wait_reject_ms=settings.ADMISSION_DB_POOL_WAIT_REJECT_MS,
    )


async def record_queue_age_sentinel(
    *,
    redis_client: QueueAgeSentinelClient,
    queue_name: str,
    member_id: str,
    published_at: float | None = None,
) -> None:
    """Best-effort queue-age sentinel write after publish."""

    try:
        key = QUEUE_AGE_ZSET_KEY.format(queue_name=queue_name)
        await _resolve(
            redis_client.zadd(
                key,
                {member_id: published_at or time.time()},
                nx=True,
            )
        )
    except Exception:  # noqa: BLE001 - sentinel failures never block publish.
        logger.warning(
            "admission_queue_age_sentinel_write_failed",
            extra={"queue_name": queue_name},
        )


async def clear_queue_age_sentinel(
    *,
    redis_client: QueueAgeSentinelClient,
    queue_name: str,
    member_id: str,
) -> None:
    """Best-effort queue-age sentinel removal at task entry."""

    try:
        key = QUEUE_AGE_ZSET_KEY.format(queue_name=queue_name)
        await _resolve(redis_client.zrem(key, member_id))
    except Exception:  # noqa: BLE001 - cleanup failures never fail tasks.
        logger.warning(
            "admission_queue_age_sentinel_clear_failed",
            extra={"queue_name": queue_name},
        )


async def clear_empty_queue_age_sentinels(
    *,
    redis_client: EmptyQueueAgeSentinelCleanupClient,
    queue_name: str,
    older_than_or_at: float | None = None,
) -> None:
    """Best-effort removal of stale age sentinels for a known-empty queue."""

    try:
        key = QUEUE_AGE_ZSET_KEY.format(queue_name=queue_name)
        cutoff = older_than_or_at if older_than_or_at is not None else time.time()
        await _resolve(redis_client.zremrangebyscore(key, "-inf", cutoff))
    except Exception:  # noqa: BLE001 - cleanup failures never affect health reads.
        logger.warning(
            "admission_empty_queue_age_sentinel_cleanup_failed",
            extra={"queue_name": queue_name},
        )


async def _resolve(value: Awaitable[Any] | Any) -> Any:
    if isawaitable(value):
        return await value
    return value


__all__ = [
    "EmptyQueueAgeSentinelCleanupClient",
    "QueueAgeSentinelClient",
    "admission_thresholds_from_settings",
    "clear_empty_queue_age_sentinels",
    "clear_queue_age_sentinel",
    "record_queue_age_sentinel",
]
