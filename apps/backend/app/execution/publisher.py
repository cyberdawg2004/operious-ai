"""Execution publishing boundary.

Orchestration services emit execution intent through this Protocol.
Concrete transports, such as Celery, live behind the boundary.
"""

from __future__ import annotations

from typing import Protocol


class ExecutionPublisher(Protocol):
    async def publish_execution(
        self,
        execution_id: str,
    ) -> None:
        ...


__all__ = ["ExecutionPublisher"]
