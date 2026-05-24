"""Execution publishing boundary.

Orchestration services emit execution intent through this Protocol.
Concrete transports, such as Celery, live behind the boundary.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.queue_admission import QueueBackpressureError


class ExecutionPublisher(Protocol):
    async def publish_execution(
        self,
        execution_id: str,
    ) -> None:
        ...


@runtime_checkable
class QueueBackpressureCheck(Protocol):
    async def check_backpressure(
        self,
        *,
        tenant_id: str | None = None,
        dispatch_id: str | None = None,
    ) -> None:
        ...


__all__ = [
    "ExecutionPublisher",
    "QueueBackpressureCheck",
    "QueueBackpressureError",
]
