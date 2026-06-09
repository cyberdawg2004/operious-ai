"""Redis queue depth admission and health helpers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from inspect import isawaitable
from typing import Any, Literal, Protocol

from app.core.queue_depth import (
    QueueDepthProvider,
    QueueDepthSample,
    RedisQueueDepthProvider,
)
from app.queues import (
    ALL_QUEUES,
    QUEUE_DIAGNOSTIC_NORMAL,
)

QueueHealthStatus = Literal["ok", "warn", "critical", "unknown"]


class QueueDepthClient(Protocol):
    def llen(self, name: str) -> Awaitable[int] | int:
        ...


class TenantQueueQoSClient(QueueDepthClient, Protocol):
    def get(self, key: str) -> Awaitable[object | None] | object | None:
        ...

    def incr(self, key: str) -> Awaitable[int] | int:
        ...

    def decr(self, key: str) -> Awaitable[int] | int:
        ...

    def expire(self, key: str, seconds: int) -> Awaitable[bool] | bool:
        ...


class QueueBackpressureError(RuntimeError):
    """Raised when a broker queue is above its admission threshold."""

    reason = "queue_backpressure"

    def __init__(
        self,
        *,
        queue_name: str,
        queue_depth: int,
        max_queue_depth: int,
        logical_queue: str | None = None,
        tenant_id: str | None = None,
        dispatch_id: str | None = None,
        reason: str | None = None,
    ) -> None:
        logical = logical_queue or queue_name
        effective_reason = reason or self.reason
        super().__init__(
            f"{effective_reason}: "
            f"{logical} ({queue_name}) depth {queue_depth} exceeds max "
            f"{max_queue_depth}"
        )
        self.reason = effective_reason
        self.logical_queue = logical
        self.queue_name = queue_name
        self.queue_depth = queue_depth
        self.max_queue_depth = max_queue_depth
        self.tenant_id = tenant_id
        self.dispatch_id = dispatch_id


@dataclass(frozen=True, slots=True)
class QueueDepthLimit:
    logical_name: str
    queue_name: str
    max_depth: int
    warn_depth: int | None = None


@dataclass(frozen=True, slots=True)
class QueueDepthReport:
    depth: int
    limit: int
    status: QueueHealthStatus
    queue_name: str | None = None
    age_seconds: float | None = None
    error: str | None = None
    messages_ready: int | None = None
    messages_unacknowledged: int | None = None
    messages: int | None = None


class RedisQueueDepthAdmission:
    """Check queue depth before publishing new Celery work.

    The class name is kept for compatibility with existing callers. New
    production composition should pass ``queue_depth_provider`` so the
    broker-specific read lives behind the provider seam.
    """

    def __init__(
        self,
        *,
        redis_client: QueueDepthClient | None = None,
        queue_depth_provider: QueueDepthProvider | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if queue_depth_provider is None:
            if redis_client is None:
                raise ValueError(
                    "RedisQueueDepthAdmission requires a depth provider "
                    "or redis client"
                )
            queue_depth_provider = RedisQueueDepthProvider(redis_client)
        self._queue_depth_provider = queue_depth_provider
        self._logger = logger or logging.getLogger(__name__)

    async def check(
        self,
        *,
        logical_queue: str,
        queue_name: str,
        max_queue_depth: int,
        tenant_id: str | None = None,
        dispatch_id: str | None = None,
    ) -> None:
        try:
            sample = await self._queue_depth_provider.get_queue_depth(queue_name)
            depth = sample.depth
        except Exception as exc:  # noqa: BLE001 - processing admission fails closed.
            self._logger.warning(
                "queue_depth_check_failed",
                extra={
                    "logical_queue": logical_queue,
                    "queue_name": queue_name,
                    "tenant_id": tenant_id,
                    "dispatch_id": dispatch_id,
                    "error": exc.__class__.__name__,
                },
            )
            raise QueueBackpressureError(
                logical_queue=logical_queue,
                queue_name=queue_name,
                queue_depth=max_queue_depth + 1,
                max_queue_depth=max_queue_depth,
                tenant_id=tenant_id,
                dispatch_id=dispatch_id,
                reason="queue_depth_unavailable",
            ) from exc
        if depth <= max_queue_depth:
            return
        self._logger.warning(
            "queue_backpressure_triggered",
            extra={
                "logical_queue": logical_queue,
                "queue_name": queue_name,
                "current_depth": depth,
                "configured_limit": max_queue_depth,
                "tenant_id": tenant_id,
                "dispatch_id": dispatch_id,
            },
        )
        raise QueueBackpressureError(
            logical_queue=logical_queue,
            queue_name=queue_name,
            queue_depth=depth,
            max_queue_depth=max_queue_depth,
            tenant_id=tenant_id,
            dispatch_id=dispatch_id,
        )


async def collect_queue_depth_reports(
    *,
    limits: tuple[QueueDepthLimit, ...],
    queue_depth_provider: QueueDepthProvider | None = None,
    redis_client: QueueDepthClient | None = None,
    operation_timeout: float | None = None,
) -> dict[str, QueueDepthReport]:
    if queue_depth_provider is None:
        if redis_client is None:
            raise ValueError(
                "collect_queue_depth_reports requires a depth provider "
                "or redis client"
            )
        queue_depth_provider = RedisQueueDepthProvider(redis_client)

    async def _collect(limit: QueueDepthLimit) -> tuple[str, QueueDepthReport]:
        try:
            sample_coro = queue_depth_provider.get_queue_depth(limit.queue_name)
            sample = (
                await asyncio.wait_for(sample_coro, timeout=operation_timeout)
                if operation_timeout is not None
                else await sample_coro
            )
        except Exception:  # noqa: BLE001 - health reports must capture.
            return (
                limit.logical_name,
                QueueDepthReport(
                    depth=0,
                    limit=limit.max_depth,
                    status="unknown",
                    queue_name=limit.queue_name,
                    error=_provider_error_name(queue_depth_provider),
                ),
            )
        return (
            limit.logical_name,
            _report_from_sample(
                sample=sample,
                limit=limit,
            ),
        )

    return dict(await asyncio.gather(*(_collect(limit) for limit in limits)))


def _report_from_sample(
    *,
    sample: QueueDepthSample,
    limit: QueueDepthLimit,
) -> QueueDepthReport:
    return QueueDepthReport(
        depth=sample.depth,
        limit=limit.max_depth,
        status=queue_depth_status(
            depth=sample.depth,
            warn_depth=limit.warn_depth,
            critical_depth=limit.max_depth,
        ),
        queue_name=limit.queue_name,
        messages_ready=sample.messages_ready,
        messages_unacknowledged=sample.messages_unacknowledged,
        messages=sample.messages,
    )


def _provider_error_name(provider: QueueDepthProvider) -> str:
    backend = getattr(provider, "backend", None)
    if backend == "redis":
        return "redis_unavailable"
    if backend == "rabbitmq":
        return "rabbitmq_unavailable"
    return "queue_depth_unavailable"


def queue_depth_status(
    *,
    depth: int,
    warn_depth: int | None = None,
    critical_depth: int = 2000,
) -> QueueHealthStatus:
    warn = 500 if warn_depth is None else warn_depth
    critical = critical_depth
    if critical < 1:
        return "critical"
    if depth >= critical:
        return "critical"
    if depth >= warn:
        return "warn"
    return "ok"


async def admit_tenant_queue_publish(
    *,
    redis_client: TenantQueueQoSClient,
    logical_queue: str,
    queue_name: str,
    tenant_id: str | None,
    max_tenant_depth: int,
    dispatch_id: str | None = None,
    ttl_seconds: int = 86_400,
) -> None:
    """Reserve one per-tenant slot before publishing to a shared queue."""

    if tenant_id is None:
        return
    if max_tenant_depth < 1:
        raise QueueBackpressureError(
            logical_queue=logical_queue,
            queue_name=queue_name,
            queue_depth=1,
            max_queue_depth=max_tenant_depth,
            tenant_id=tenant_id,
            dispatch_id=dispatch_id,
            reason="tenant_queue_backpressure",
        )
    key = tenant_queue_backlog_key(queue_name=queue_name, tenant_id=tenant_id)
    try:
        count = await _resolve_int(redis_client.incr(key))
        if count == 1:
            await _resolve_bool(redis_client.expire(key, ttl_seconds))
    except Exception as exc:  # noqa: BLE001 - QoS admission is processing-critical.
        logging.getLogger(__name__).warning(
            "tenant_queue_qos_check_failed",
            extra={
                "logical_queue": logical_queue,
                "queue_name": queue_name,
                "tenant_id": tenant_id,
                "dispatch_id": dispatch_id,
                "error": exc.__class__.__name__,
            },
        )
        raise QueueBackpressureError(
            logical_queue=logical_queue,
            queue_name=queue_name,
            queue_depth=max_tenant_depth + 1,
            max_queue_depth=max_tenant_depth,
            tenant_id=tenant_id,
            dispatch_id=dispatch_id,
            reason="tenant_queue_qos_unavailable",
        ) from exc
    if count <= max_tenant_depth:
        return
    await release_tenant_queue_publish(
        redis_client=redis_client,
        queue_name=queue_name,
        tenant_id=tenant_id,
    )
    raise QueueBackpressureError(
        logical_queue=logical_queue,
        queue_name=queue_name,
        queue_depth=count,
        max_queue_depth=max_tenant_depth,
        tenant_id=tenant_id,
        dispatch_id=dispatch_id,
        reason="tenant_queue_backpressure",
    )


async def release_tenant_queue_publish(
    *,
    redis_client: TenantQueueQoSClient,
    queue_name: str,
    tenant_id: str | None,
) -> None:
    """Release one per-tenant queue slot when work starts or publish fails."""

    if tenant_id is None:
        return
    key = tenant_queue_backlog_key(queue_name=queue_name, tenant_id=tenant_id)
    try:
        value = await _resolve_any(redis_client.get(key))
        if value is None or int(value) <= 0:
            return
        await _resolve_int(redis_client.decr(key))
    except Exception as exc:  # noqa: BLE001 - release is best-effort cleanup.
        logging.getLogger(__name__).warning(
            "tenant_queue_qos_release_failed",
            extra={
                "queue_name": queue_name,
                "tenant_id": tenant_id,
                "error": exc.__class__.__name__,
            },
        )


def tenant_queue_backlog_key(*, queue_name: str, tenant_id: str) -> str:
    return f"queue:tenant_backlog:{queue_name}:{tenant_id}"


async def _resolve_int(value: Awaitable[int] | int) -> int:
    if isawaitable(value):
        return await value
    return value


async def _resolve_bool(value: Awaitable[bool] | bool) -> bool:
    if isawaitable(value):
        return await value
    return value


async def _resolve_any(value: Awaitable[Any] | Any) -> Any:
    if isawaitable(value):
        return await value
    return value


def aggregate_queue_status(
    reports: Mapping[str, QueueDepthReport],
) -> Literal["ok", "degraded", "unavailable"]:
    statuses = {report.status for report in reports.values()}
    if "unknown" in statuses:
        return "unavailable"
    if "critical" in statuses or "warn" in statuses:
        return "degraded"
    return "ok"


def celery_queue_depth_limits(settings: Any) -> tuple[QueueDepthLimit, ...]:
    warn_depth = int(settings.ADMISSION_QUEUE_DEPTH_WARN)
    critical_depth = int(settings.ADMISSION_QUEUE_DEPTH_REJECT)
    physical_limits = tuple(
        QueueDepthLimit(
            logical_name=queue_name,
            queue_name=queue_name,
            max_depth=critical_depth,
            warn_depth=warn_depth,
        )
        for queue_name in ALL_QUEUES
    )
    legacy_limits = (
        QueueDepthLimit(
            logical_name="diagnostic",
            queue_name=QUEUE_DIAGNOSTIC_NORMAL,
            max_depth=critical_depth,
            warn_depth=warn_depth,
        ),
    )
    return (*physical_limits, *legacy_limits)


__all__ = [
    "QueueBackpressureError",
    "QueueDepthClient",
    "QueueDepthLimit",
    "QueueDepthReport",
    "QueueHealthStatus",
    "RedisQueueDepthAdmission",
    "TenantQueueQoSClient",
    "aggregate_queue_status",
    "admit_tenant_queue_publish",
    "celery_queue_depth_limits",
    "collect_queue_depth_reports",
    "queue_depth_status",
    "release_tenant_queue_publish",
    "tenant_queue_backlog_key",
]
