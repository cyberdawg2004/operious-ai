"""AdmissionGate evaluates queue pressure without owning persistence."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from inspect import isawaitable
from typing import Any, Protocol, cast

from app.hardening.admission.models import (
    AdmissionChannelClass,
    AdmissionDecision,
    AdmissionOutcome,
    AdmissionReason,
)

logger = logging.getLogger(__name__)

QUEUE_AGE_ZSET_KEY = "queue:age:{queue_name}"

_ASYNC_TICKET_CHANNELS = frozenset(
    {
        "email",
        "lark",
        "shulex",
        "zendesk",
        "ticket",
        "webhook",
        "whatsapp",
        "whatsapp_webhook",
        "async_ticket",
    }
)
_BATCH_CHANNELS = frozenset({"batch", "batch_ingest", "batch_ingestion"})
_REALTIME_CHAT_CHANNELS = frozenset(
    {
        "realtime_chat",
        "whatsapp_live",
        "whatsapp_realtime",
        "livechat",
        "live_chat",
        "webchat",
        "web_chat",
    }
)
_VOICE_CHANNELS = frozenset({"voice", "call", "calls"})
_INTERNAL_EXECUTION_CHANNELS = frozenset(
    {
        "internal_execution",
        "execution",
        "execution_publish",
        "execution_recovery",
        "diagnostic_execution",
        "diagnostic_internal",
    }
)


class AdmissionRedisClient(Protocol):
    """Redis subset used by admission checks and queue-age sentinels."""

    def llen(self, name: str) -> Awaitable[int] | int:
        ...

    def info(self, section: str | None = None) -> Awaitable[Mapping[str, Any]] | Mapping[str, Any]:
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


class AdmissionQueueDepthProvider(Protocol):
    async def get_queue_depth(self, queue_name: str) -> Any:
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


@dataclass(frozen=True, slots=True)
class _TelemetrySample:
    value: float | int | None
    available: bool
    unavailable_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _QueueDepthSample:
    depth: int


class _RedisAdmissionQueueDepthProvider:
    def __init__(self, redis_client: AdmissionRedisClient) -> None:
        self._redis = redis_client

    async def get_queue_depth(self, queue_name: str) -> _QueueDepthSample:
        depth = int(await _resolve(self._redis.llen(queue_name)) or 0)
        return _QueueDepthSample(depth=depth)


class AdmissionGate:
    """Stateless evaluator for inbound queue admission."""

    def __init__(
        self,
        *,
        redis_client: AdmissionRedisClient,
        thresholds: AdmissionGateThresholds,
        queue_depth_provider: AdmissionQueueDepthProvider | None = None,
    ) -> None:
        self._redis = redis_client
        self._thresholds = thresholds
        self._queue_depth_provider = (
            queue_depth_provider
            if queue_depth_provider is not None
            else _RedisAdmissionQueueDepthProvider(redis_client)
        )

    async def evaluate(
        self,
        *,
        queue_name: str | None = None,
        queue_names: Sequence[str] | None = None,
        tenant_id: str | None = None,
        channel: str | None = None,
        request_correlation_id: str | None = None,
        db_pool_wait_ms: float | None = None,
    ) -> AdmissionDecision:
        now = datetime.now(timezone.utc)
        targets = _queue_targets(queue_name=queue_name, queue_names=queue_names)
        queue_identity = ",".join(targets)
        decision_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            "|".join(
                (
                    "operious-admission",
                    queue_identity,
                    tenant_id or "",
                    channel or "",
                    request_correlation_id or "",
                )
            ),
        )
        channel_class = classify_admission_channel(channel)
        redis_memory_sample = await self._redis_memory_pct_sample(
            queue_name=queue_identity
        )
        queue_depth_sample = await self._queue_depth_sample(queue_names=targets)
        queue_age_sample = await self._queue_age_seconds_sample(queue_names=targets)
        redis_memory_pct = (
            float(redis_memory_sample.value)
            if redis_memory_sample.value is not None
            else None
        )
        queue_depth = int(queue_depth_sample.value or 0)
        queue_age_seconds = (
            float(queue_age_sample.value)
            if queue_age_sample.value is not None
            else None
        )
        unavailable_reasons = _dedupe_reasons(
            (
                *redis_memory_sample.unavailable_reasons,
                *queue_depth_sample.unavailable_reasons,
                *queue_age_sample.unavailable_reasons,
            )
        )

        def decision(
            *,
            outcome: AdmissionOutcome,
            reason: AdmissionReason | None,
            retry_after_seconds: int,
        ) -> AdmissionDecision:
            return self._decision(
                decision_id=decision_id,
                outcome=outcome,
                reason=reason,
                queue_name=queue_identity,
                queue_depth=queue_depth,
                queue_age_seconds=queue_age_seconds,
                redis_memory_pct=redis_memory_pct,
                db_pool_wait_ms=db_pool_wait_ms,
                retry_after_seconds=retry_after_seconds,
                evaluated_at=now,
                queue_depth_available=queue_depth_sample.available,
                queue_age_available=queue_age_sample.available,
                redis_memory_available=redis_memory_sample.available,
                unavailable_reasons=unavailable_reasons,
                channel_class=channel_class,
            )

        if (
            redis_memory_pct is not None
            and redis_memory_pct >= self._thresholds.redis_memory_pct_reject
        ):
            return decision(
                outcome=AdmissionOutcome.REJECT,
                reason=AdmissionReason.REDIS_MEMORY_PRESSURE,
                retry_after_seconds=60,
            )

        if (
            db_pool_wait_ms is not None
            and db_pool_wait_ms >= self._thresholds.db_pool_wait_reject_ms
        ):
            return decision(
                outcome=AdmissionOutcome.REJECT,
                reason=AdmissionReason.DB_POOL_PRESSURE,
                retry_after_seconds=60,
            )
        if (
            db_pool_wait_ms is not None
            and db_pool_wait_ms >= self._thresholds.db_pool_wait_warn_ms
        ):
            return decision(
                outcome=AdmissionOutcome.DEFER,
                reason=AdmissionReason.DB_POOL_PRESSURE,
                retry_after_seconds=30,
            )

        if queue_depth >= self._thresholds.queue_depth_reject:
            return decision(
                outcome=AdmissionOutcome.REJECT,
                reason=AdmissionReason.QUEUE_DEPTH_EXCEEDED,
                retry_after_seconds=30,
            )
        if queue_depth >= self._thresholds.queue_depth_warn:
            return decision(
                outcome=AdmissionOutcome.DEFER,
                reason=AdmissionReason.QUEUE_DEPTH_EXCEEDED,
                retry_after_seconds=15,
            )

        if (
            queue_age_seconds is not None
            and queue_age_seconds >= self._thresholds.queue_age_reject_seconds
        ):
            return decision(
                outcome=AdmissionOutcome.REJECT,
                reason=AdmissionReason.QUEUE_AGE_EXCEEDED,
                retry_after_seconds=60,
            )
        if (
            queue_age_seconds is not None
            and queue_age_seconds >= self._thresholds.queue_age_warn_seconds
        ):
            return decision(
                outcome=AdmissionOutcome.DEFER,
                reason=AdmissionReason.QUEUE_AGE_EXCEEDED,
                retry_after_seconds=20,
            )

        if unavailable_reasons:
            # Realtime chat can defer until pressure clears. Voice is live
            # media, so unknown capacity fails closed instead of queueing a
            # customer into silence.
            if channel_class is AdmissionChannelClass.REALTIME_CHAT:
                return decision(
                    outcome=AdmissionOutcome.DEFER,
                    reason=AdmissionReason.TELEMETRY_UNAVAILABLE_REALTIME,
                    retry_after_seconds=15,
                )
            if channel_class is AdmissionChannelClass.VOICE:
                return decision(
                    outcome=AdmissionOutcome.REJECT,
                    reason=AdmissionReason.TELEMETRY_UNAVAILABLE_VOICE,
                    retry_after_seconds=10,
                )
            # Telemetry is a monitoring probe, not a backpressure signal: every
            # real signal checked above (queue depth/age, redis memory, db pool
            # wait) already reported healthy or defaulted to healthy when
            # unavailable. A telemetry outage alone must not defer-to-death
            # otherwise-healthy processing traffic. `telemetry_unavailable`
            # remains true on the decision for observability/alerting.
            return decision(
                outcome=AdmissionOutcome.ADMIT,
                reason=AdmissionReason.TELEMETRY_UNAVAILABLE_PROCESSING,
                retry_after_seconds=30,
            )

        return decision(
            outcome=AdmissionOutcome.ADMIT,
            reason=None,
            retry_after_seconds=30,
        )

    async def redis_memory_pct(self) -> float | None:
        """Return Redis memory pressure, or None when unbounded/unavailable."""

        sample = await self._redis_memory_pct_sample(queue_name=None)
        return float(sample.value) if sample.value is not None else None

    async def queue_age_seconds(self, *, queue_name: str) -> float | None:
        """Return oldest message age for a queue, if the sentinel exists."""

        sample = await self._queue_age_seconds_sample(queue_names=(queue_name,))
        return float(sample.value) if sample.value is not None else None

    async def _redis_memory_pct_sample(self, *, queue_name: str | None) -> _TelemetrySample:
        try:
            info = await _resolve(self._redis.info("memory"))
            used = int(info.get("used_memory", 0))
            max_memory = int(info.get("maxmemory", 0))
            if max_memory <= 0:
                return _TelemetrySample(value=None, available=True)
            return _TelemetrySample(
                value=round((used / max_memory) * 100, 2),
                available=True,
            )
        except Exception:  # noqa: BLE001 - admission policy handles telemetry loss.
            logger.warning(
                "admission_redis_memory_check_failed",
                extra={"queue_name": queue_name},
            )
            return _TelemetrySample(
                value=None,
                available=False,
                unavailable_reasons=("redis_memory_unavailable",),
            )

    async def _queue_depth_sample(self, *, queue_names: Sequence[str]) -> _TelemetrySample:
        depth = 0
        unavailable_reasons: list[str] = []
        for queue_name in queue_names:
            sample = await self._single_queue_depth_sample(queue_name=queue_name)
            depth += int(sample.value or 0)
            unavailable_reasons.extend(sample.unavailable_reasons)
        return _TelemetrySample(
            value=depth,
            available=not unavailable_reasons,
            unavailable_reasons=tuple(unavailable_reasons),
        )

    async def _single_queue_depth_sample(self, *, queue_name: str) -> _TelemetrySample:
        try:
            sample = await self._queue_depth_provider.get_queue_depth(queue_name)
            return _TelemetrySample(value=sample.depth, available=True)
        except Exception:  # noqa: BLE001 - admission policy handles telemetry loss.
            logger.warning(
                "admission_queue_depth_check_failed",
                extra={"queue_name": queue_name},
            )
            return _TelemetrySample(
                value=0,
                available=False,
                unavailable_reasons=(f"queue_depth_unavailable:{queue_name}",),
            )

    async def _queue_age_seconds_sample(
        self,
        *,
        queue_names: Sequence[str],
    ) -> _TelemetrySample:
        ages: list[float] = []
        unavailable_reasons: list[str] = []
        for queue_name in queue_names:
            sample = await self._single_queue_age_seconds_sample(queue_name=queue_name)
            if sample.value is not None:
                ages.append(float(sample.value))
            unavailable_reasons.extend(sample.unavailable_reasons)
        if not ages:
            return _TelemetrySample(
                value=None,
                available=not unavailable_reasons,
                unavailable_reasons=tuple(unavailable_reasons),
            )
        return _TelemetrySample(
            value=max(ages),
            available=not unavailable_reasons,
            unavailable_reasons=tuple(unavailable_reasons),
        )

    async def _single_queue_age_seconds_sample(
        self,
        *,
        queue_name: str,
    ) -> _TelemetrySample:
        try:
            key = QUEUE_AGE_ZSET_KEY.format(queue_name=queue_name)
            result = await _resolve(
                self._redis.zrange(key, 0, 0, withscores=True)
            )
            if not result:
                return _TelemetrySample(value=None, available=True)
            first = result[0]
            if not isinstance(first, tuple):
                return _TelemetrySample(value=None, available=True)
            queue_age_entry = cast(tuple[object, ...], first)
            if len(queue_age_entry) < 2:
                return _TelemetrySample(value=None, available=True)
            score = queue_age_entry[1]
            if not isinstance(score, int | float | str):
                return _TelemetrySample(value=None, available=True)
            return _TelemetrySample(
                value=round(max(0.0, time.time() - float(score)), 2),
                available=True,
            )
        except Exception:  # noqa: BLE001 - admission policy handles telemetry loss.
            logger.warning(
                "admission_queue_age_check_failed",
                extra={"queue_name": queue_name},
            )
            return _TelemetrySample(
                value=None,
                available=False,
                unavailable_reasons=(f"queue_age_unavailable:{queue_name}",),
            )

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
        queue_depth_available: bool,
        queue_age_available: bool,
        redis_memory_available: bool,
        unavailable_reasons: tuple[str, ...],
        channel_class: AdmissionChannelClass,
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
            queue_depth_available=queue_depth_available,
            queue_age_available=queue_age_available,
            redis_memory_available=redis_memory_available,
            unavailable_reasons=unavailable_reasons,
            channel_class=channel_class,
        )


async def _resolve(value: Awaitable[Any] | Any) -> Any:
    if isawaitable(value):
        return await value
    return value


def _queue_targets(
    *,
    queue_name: str | None,
    queue_names: Sequence[str] | None,
) -> tuple[str, ...]:
    targets = tuple(_non_empty_names(queue_names or ()))
    if queue_name is not None:
        targets = (queue_name, *targets)
    deduped = tuple(dict.fromkeys(targets))
    if not deduped:
        raise ValueError("AdmissionGate requires at least one queue name")
    return deduped


def _non_empty_names(values: Iterable[str]) -> Iterable[str]:
    for value in values:
        stripped = value.strip()
        if not stripped:
            raise ValueError("queue names must be non-empty")
        yield stripped


def classify_admission_channel(channel: str | None) -> AdmissionChannelClass:
    """Return the risk class for an admission channel."""

    normalized = (channel or "").strip().lower().replace("-", "_")
    if normalized in _REALTIME_CHAT_CHANNELS:
        return AdmissionChannelClass.REALTIME_CHAT
    if normalized in _VOICE_CHANNELS:
        return AdmissionChannelClass.VOICE
    if normalized in _BATCH_CHANNELS:
        return AdmissionChannelClass.BATCH
    if normalized in _INTERNAL_EXECUTION_CHANNELS:
        return AdmissionChannelClass.INTERNAL_EXECUTION
    if normalized in _ASYNC_TICKET_CHANNELS:
        return AdmissionChannelClass.ASYNC_TICKET
    if "livechat" in normalized or "webchat" in normalized:
        return AdmissionChannelClass.REALTIME_CHAT
    if "voice" in normalized or "call" in normalized:
        return AdmissionChannelClass.VOICE
    if "batch" in normalized:
        return AdmissionChannelClass.BATCH
    if "execution" in normalized or "diagnostic" in normalized:
        return AdmissionChannelClass.INTERNAL_EXECUTION
    return AdmissionChannelClass.ASYNC_TICKET


def _dedupe_reasons(reasons: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(reason for reason in reasons if reason))


__all__ = [
    "AdmissionGate",
    "AdmissionGateThresholds",
    "AdmissionRedisClient",
    "QUEUE_AGE_ZSET_KEY",
    "classify_admission_channel",
]
