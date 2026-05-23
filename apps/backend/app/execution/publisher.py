"""Execution publishing boundary.

Orchestration services emit execution intent through this Protocol.
Concrete transports, such as Celery, live behind the boundary.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class QueueBackpressureError(RuntimeError):
    """Raised when the execution queue is above the admission threshold."""

    reason = "queue_backpressure"

    def __init__(
        self,
        *,
        queue_name: str,
        queue_depth: int,
        max_queue_depth: int,
    ) -> None:
        super().__init__(
            "execution queue backpressure: "
            f"{queue_name} depth {queue_depth} exceeds max {max_queue_depth}"
        )
        self.queue_name = queue_name
        self.queue_depth = queue_depth
        self.max_queue_depth = max_queue_depth


class ExecutionPublisher(Protocol):
    async def publish_execution(
        self,
        execution_id: str,
    ) -> None:
        ...


@runtime_checkable
class QueueBackpressureCheck(Protocol):
    async def check_backpressure(self) -> None:
        ...


__all__ = [
    "ExecutionPublisher",
    "QueueBackpressureCheck",
    "QueueBackpressureError",
]
