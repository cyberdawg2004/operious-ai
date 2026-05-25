"""Redis queue depth admission and health helpers."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from inspect import isawaitable
from typing import Any, Literal, Protocol

from app.queues import (
    QUEUE_DIAGNOSTIC_NORMAL,
    QUEUE_ESCALATION,
    QUEUE_QA,
    QUEUE_SOP_INTELLIGENCE,
    QUEUE_SUPERVISOR,
)

QueueHealthStatus = Literal["ok", "degraded", "saturated", "unavailable"]


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
        depth = await _resolve_depth(self._redis_client.llen(queue_name))
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
) -> dict[str, QueueDepthReport]:
    reports: dict[str, QueueDepthReport] = {}
    for limit in limits:
        try:
            depth = await _resolve_depth(redis_client.llen(limit.queue_name))
        except Exception as exc:  # noqa: BLE001 - health reports must capture.
            reports[limit.logical_name] = QueueDepthReport(
                depth=-1,
                limit=limit.max_depth,
                status="unavailable",
                queue_name=limit.queue_name,
                error=exc.__class__.__name__,
            )
            continue
        reports[limit.logical_name] = QueueDepthReport(
            depth=depth,
            limit=limit.max_depth,
            status=queue_depth_status(depth=depth, limit=limit.max_depth),
            queue_name=limit.queue_name,
        )
    return reports


def queue_depth_status(*, depth: int, limit: int) -> QueueHealthStatus:
    if limit < 1:
        return "saturated"
    if depth > limit:
        return "saturated"
    if depth > limit * 0.8:
        return "degraded"
    return "ok"


async def _resolve_depth(value: Awaitable[int] | int) -> int:
    if isawaitable(value):
        return await value
    return value


def aggregate_queue_status(
    reports: Mapping[str, QueueDepthReport],
) -> Literal["ok", "degraded", "unavailable"]:
    statuses = {report.status for report in reports.values()}
    if "unavailable" in statuses:
        return "unavailable"
    if "saturated" in statuses or "degraded" in statuses:
        return "degraded"
    return "ok"


def celery_queue_depth_limits(settings: Any) -> tuple[QueueDepthLimit, ...]:
    return (
        QueueDepthLimit(
            logical_name="diagnostic",
            queue_name=QUEUE_DIAGNOSTIC_NORMAL,
            max_depth=settings.EXECUTION_QUEUE_MAX_DEPTH,
        ),
        QueueDepthLimit(
            logical_name="escalation",
            queue_name=QUEUE_ESCALATION,
            max_depth=settings.ESCALATION_QUEUE_MAX_DEPTH,
        ),
        QueueDepthLimit(
            logical_name="supervisor",
            queue_name=QUEUE_SUPERVISOR,
            max_depth=settings.SUPERVISOR_QUEUE_MAX_DEPTH,
        ),
        QueueDepthLimit(
            logical_name="qa",
            queue_name=QUEUE_QA,
            max_depth=settings.QA_QUEUE_MAX_DEPTH,
        ),
        QueueDepthLimit(
            logical_name="sop_intelligence",
            queue_name=QUEUE_SOP_INTELLIGENCE,
            max_depth=settings.SOP_INTELLIGENCE_QUEUE_MAX_DEPTH,
        ),
    )


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
