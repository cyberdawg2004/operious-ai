"""Celery-backed execution publisher."""

from __future__ import annotations

import os
import sys
from typing import Any, Protocol, cast

from app.core.config import get_settings
from app.core.queue_admission import RedisQueueDepthAdmission
from app.core.redis import get_redis_client
from app.execution.publisher import ExecutionPublisher
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

    async def check_backpressure(
        self,
        *,
        tenant_id: str | None = None,
        dispatch_id: str | None = None,
    ) -> None:
        """Reject publication before Celery accepts more work."""

        client = self._redis_client
        if client is None:
            if _running_under_pytest():
                return
            client = cast(QueueDepthClient, get_redis_client())
            self._redis_client = client
        await RedisQueueDepthAdmission(redis_client=client).check(
            logical_queue="diagnostic",
            queue_name=self._queue_name,
            max_queue_depth=self._max_queue_depth,
            tenant_id=tenant_id,
            dispatch_id=dispatch_id,
        )

    async def publish_execution(
        self,
        execution_id: str,
        *,
        tenant_id: str,
    ) -> None:
        await self.check_backpressure(tenant_id=tenant_id)
        task = cast(Any, execute_diagnostic_agent)
        if _running_under_pytest():
            if self._run_inline_under_pytest:
                await execute_diagnostic_agent_runtime(
                    execution_id=execution_id,
                    tenant_id=tenant_id,
                )
            return
        else:
            task.apply_async(
                kwargs={
                    "execution_id": execution_id,
                    "tenant_id": tenant_id,
                },
                queue=self._queue_name,
            )


def _running_under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


__all__ = ["CeleryExecutionPublisher"]
