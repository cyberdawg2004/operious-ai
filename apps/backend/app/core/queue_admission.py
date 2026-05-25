"""Redis queue depth admission and health helpers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from inspect import isawaitable
from typing import Any, Literal, Protocol

from app.queues import (
    ALL_QUEUES,
    QUEUE_DIAGNOSTIC_NORMAL,
)

QueueHealthStatus = Literal["ok", "warn", "critical", "unknown"]


class QueueDepthClient(Protocol):
    def llen(self, name: str) -> Awaitable[int] | int:
        ...


class QueueBackpressureError(RuntimeError):
    """Raised when a Redis-backed queue is above its admission threshold."""

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
    ) -> None:
        logical = logical_queue or queue_name
        super().__init__(
            "queue backpressure: "
            f"{logical} ({queue_name}) depth {queue_depth} exceeds max "
            f"{max_queue_depth}"
        )
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


class RedisQueueDepthAdmission:
    """Check Redis queue depth before publishing new Celery work."""

    def __init__(
        self,
        *,
        redis_client: QueueDepthClient,
        logger: logging.Logger | None = None,
    ) -> None:
        self._redis_client = redis_client
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
            depth = await _resolve_depth(self._redis_client.llen(queue_name))
        except Exception as exc:  # noqa: BLE001 - admission must fail open here.
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
            depth = 0
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
    redis_client: QueueDepthClient,
    limits: tuple[QueueDepthLimit, ...],
    operation_timeout: float | None = None,
) -> dict[str, QueueDepthReport]:
    async def _collect(limit: QueueDepthLimit) -> tuple[str, QueueDepthReport]:
        try:
            depth_coro = _resolve_depth(redis_client.llen(limit.queue_name))
            depth = (
                await asyncio.wait_for(depth_coro, timeout=operation_timeout)
                if operation_timeout is not None
                else await depth_coro
            )
        except Exception:  # noqa: BLE001 - health reports must capture.
            return (
                limit.logical_name,
                QueueDepthReport(
                    depth=0,
                    limit=limit.max_depth,
                    status="unknown",
                    queue_name=limit.queue_name,
                    error="redis_unavailable",
                ),
            )
        return (
            limit.logical_name,
            QueueDepthReport(
                depth=depth,
                limit=limit.max_depth,
                status=queue_depth_status(
                    depth=depth,
                    warn_depth=limit.warn_depth,
                    critical_depth=limit.max_depth,
                ),
                queue_name=limit.queue_name,
            ),
        )

    return dict(await asyncio.gather(*(_collect(limit) for limit in limits)))


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


async def _resolve_depth(value: Awaitable[int] | int) -> int:
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
    "aggregate_queue_status",
    "celery_queue_depth_limits",
    "collect_queue_depth_reports",
    "queue_depth_status",
]
