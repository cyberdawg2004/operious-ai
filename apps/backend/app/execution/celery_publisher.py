"""Celery-backed execution publisher."""

from __future__ import annotations

import os
import sys
from typing import Any, Protocol, cast

from app.core.config import get_settings
from app.core.redis import get_redis_client
from app.execution.publisher import ExecutionPublisher, QueueBackpressureError
from app.workers.agent_tasks import (
    execute_diagnostic_agent,
    execute_diagnostic_agent_runtime,
)


class QueueDepthClient(Protocol):
    async def llen(self, name: str) -> int:
        ...


class CeleryExecutionPublisher(ExecutionPublisher):
    """Publish execution intents through the worker transport."""

    def __init__(
        self,
        *,
        redis_client: QueueDepthClient | None = None,
        queue_name: str | None = None,
        max_queue_depth: int | None = None,
        run_inline_under_pytest: bool | None = None,
    ) -> None:
        settings = get_settings()
        self._redis_client = redis_client
        self._queue_name = queue_name or settings.EXECUTION_QUEUE_NAME
        self._max_queue_depth = (
            max_queue_depth
            if max_queue_depth is not None
            else settings.EXECUTION_QUEUE_MAX_DEPTH
        )
        self._run_inline_under_pytest = (
            redis_client is None
            if run_inline_under_pytest is None
            else run_inline_under_pytest
        )

    async def check_backpressure(self) -> None:
        """Reject publication before Celery accepts more work."""

        client = self._redis_client
        if client is None:
            if _running_under_pytest():
                return
            client = cast(QueueDepthClient, get_redis_client())
            self._redis_client = client
        queue_depth = await client.llen(self._queue_name)
        if queue_depth > self._max_queue_depth:
            raise QueueBackpressureError(
                queue_name=self._queue_name,
                queue_depth=queue_depth,
                max_queue_depth=self._max_queue_depth,
            )

    async def publish_execution(
        self,
        execution_id: str,
    ) -> None:
        await self.check_backpressure()
        task = cast(Any, execute_diagnostic_agent)
        if _running_under_pytest():
            if self._run_inline_under_pytest:
                await execute_diagnostic_agent_runtime(
                    execution_id=execution_id,
                )
            return
        else:
            task.delay(execution_id=execution_id)


def _running_under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


__all__ = ["CeleryExecutionPublisher"]
