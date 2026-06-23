"""Celery-backed execution publisher."""

from __future__ import annotations

import os
import sys
from typing import Any, Protocol, cast

from app.core.admission import (
    QueueAgeSentinelClient,
    clear_queue_age_sentinel,
    record_queue_age_sentinel,
)
from app.core.config import get_settings
from app.core.queue_depth import (
    QueueDepthProvider,
    RedisQueueDepthProvider,
    get_queue_depth_provider,
)
from app.core.queue_admission import (
    RedisQueueDepthAdmission,
    TenantQueueQoSClient,
    admit_tenant_queue_publish,
    release_tenant_queue_publish,
)
from app.core.redis import get_redis_client
from app.execution.publisher import ExecutionPublisher
from app.workers.agent_tasks import (
    execute_diagnostic_agent,
    execute_diagnostic_agent_runtime,
)
from app.workers.celery_app import enqueued_at_iso
from app.queues import QUEUE_DIAGNOSTIC_NORMAL


class QueueDepthClient(Protocol):
    async def llen(self, name: str) -> int:
        ...


class CeleryExecutionPublisher(ExecutionPublisher):
    """Publish execution intents through the worker transport."""

    def __init__(
        self,
        *,
        redis_client: QueueDepthClient | None = None,
        queue_depth_provider: QueueDepthProvider | None = None,
        queue_name: str | None = None,
        max_queue_depth: int | None = None,
        max_tenant_queue_depth: int | None = None,
        run_inline_under_pytest: bool | None = None,
    ) -> None:
        settings = get_settings()
        self._redis_client = redis_client
        self._queue_depth_provider = queue_depth_provider
        self._queue_name = queue_name or QUEUE_DIAGNOSTIC_NORMAL
        self._max_queue_depth = (
            max_queue_depth
            if max_queue_depth is not None
            else settings.EXECUTION_QUEUE_MAX_DEPTH
        )
        self._max_tenant_queue_depth = (
            max_tenant_queue_depth
            if max_tenant_queue_depth is not None
            else settings.EXECUTION_QUEUE_TENANT_MAX_DEPTH
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

        provider = self._queue_depth_provider
        if provider is None:
            client = self._redis_client
            if client is not None:
                provider = RedisQueueDepthProvider(client)
            elif _running_under_pytest():
                return
            else:
                provider = get_queue_depth_provider()
            self._queue_depth_provider = provider
        await RedisQueueDepthAdmission(queue_depth_provider=provider).check(
            logical_queue=QUEUE_DIAGNOSTIC_NORMAL,
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
        tenant_qos_admitted = False
        client = self._redis_client
        if client is None and not _running_under_pytest():
            client = cast(QueueDepthClient, get_redis_client())
            self._redis_client = client
        if client is not None:
            await admit_tenant_queue_publish(
                redis_client=cast(TenantQueueQoSClient, client),
                logical_queue=QUEUE_DIAGNOSTIC_NORMAL,
                queue_name=self._queue_name,
                tenant_id=tenant_id,
                max_tenant_depth=self._max_tenant_queue_depth,
            )
            tenant_qos_admitted = True
        task = cast(Any, execute_diagnostic_agent)
        if _running_under_pytest():
            try:
                if self._run_inline_under_pytest:
                    await execute_diagnostic_agent_runtime(
                        execution_id=execution_id,
                        tenant_id=tenant_id,
                    )
            finally:
                if tenant_qos_admitted and client is not None:
                    await release_tenant_queue_publish(
                        redis_client=cast(TenantQueueQoSClient, client),
                        queue_name=self._queue_name,
                        tenant_id=tenant_id,
                    )
            return
        # Write the sentinel before the task is dispatchable: if a worker
        # could dequeue and clear it first, the publisher's clear-on-entry
        # would be a no-op and the later write would orphan the member.
        await record_queue_age_sentinel(
            redis_client=cast(QueueAgeSentinelClient, client),
            queue_name=self._queue_name,
            member_id=execution_id,
        )
        try:
            task.apply_async(
                kwargs={
                    "execution_id": execution_id,
                    "tenant_id": tenant_id,
                    "_enqueued_at": enqueued_at_iso(),
                },
                queue=self._queue_name,
            )
        except Exception:
            await clear_queue_age_sentinel(
                redis_client=cast(QueueAgeSentinelClient, client),
                queue_name=self._queue_name,
                member_id=execution_id,
            )
            if tenant_qos_admitted and client is not None:
                await release_tenant_queue_publish(
                    redis_client=cast(TenantQueueQoSClient, client),
                    queue_name=self._queue_name,
                    tenant_id=tenant_id,
                )
            raise


def _running_under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


__all__ = ["CeleryExecutionPublisher"]
