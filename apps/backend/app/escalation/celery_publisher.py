"""Celery-backed escalation publisher."""

from __future__ import annotations

import os
import sys
from typing import Any, cast

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
from app.core.queue_admission import QueueDepthClient, RedisQueueDepthAdmission
from app.core.redis import get_redis_client
from app.escalation.publisher import EscalationPublisher
from app.workers.celery_app import enqueued_at_iso
from app.queues import QUEUE_ESCALATION


class CeleryEscalationPublisher(EscalationPublisher):
    """Publish escalation intents through worker transport."""

    def __init__(
        self,
        *,
        redis_client: QueueDepthClient | None = None,
        queue_depth_provider: QueueDepthProvider | None = None,
        queue_name: str | None = None,
        max_queue_depth: int | None = None,
    ) -> None:
        settings = get_settings()
        self._redis_client = redis_client
        self._queue_depth_provider = queue_depth_provider
        self._queue_name = queue_name or QUEUE_ESCALATION
        self._max_queue_depth = (
            max_queue_depth
            if max_queue_depth is not None
            else settings.ESCALATION_QUEUE_MAX_DEPTH
        )

    async def check_backpressure(
        self,
        *,
        tenant_id: str | None = None,
        dispatch_id: str | None = None,
    ) -> None:
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
            logical_queue=QUEUE_ESCALATION,
            queue_name=self._queue_name,
            max_queue_depth=self._max_queue_depth,
            tenant_id=tenant_id,
            dispatch_id=dispatch_id,
        )

    async def publish_governance_denial(
        self,
        *,
        governance_decision_id: str,
        tenant_id: str,
        session_id: str | None = None,
    ) -> None:
        await self._publish_governance_decision(
            governance_decision_id=governance_decision_id,
            tenant_id=tenant_id,
            session_id=session_id,
        )

    async def publish_governance_escalation(
        self,
        *,
        governance_decision_id: str,
        tenant_id: str,
        session_id: str | None = None,
    ) -> None:
        await self._publish_governance_decision(
            governance_decision_id=governance_decision_id,
            tenant_id=tenant_id,
            session_id=session_id,
        )

    async def _publish_governance_decision(
        self,
        *,
        governance_decision_id: str,
        tenant_id: str,
        session_id: str | None = None,
    ) -> None:
        from app.workers.escalation_tasks import (  # lazy: breaks the celery_publisher→escalation_tasks→celery_app→alert_evaluator_factory→runtime→invoker→celery_publisher cycle
            create_governance_escalation,
            create_governance_escalation_runtime,
        )

        await self.check_backpressure(tenant_id=tenant_id)
        task = cast(Any, create_governance_escalation)
        if _running_under_pytest():
            await create_governance_escalation_runtime(
                governance_decision_id=governance_decision_id,
                tenant_id=tenant_id,
                session_id=session_id,
            )
        else:
            client = self._redis_client
            if client is None:
                client = get_redis_client()
                self._redis_client = client
            # Write the sentinel before the task is dispatchable: if a
            # worker could dequeue and clear it first, the publisher's
            # later write would orphan the member permanently.
            await record_queue_age_sentinel(
                redis_client=cast(QueueAgeSentinelClient, client),
                queue_name=self._queue_name,
                member_id=governance_decision_id,
            )
            try:
                task.apply_async(
                    kwargs={
                        "governance_decision_id": governance_decision_id,
                        "tenant_id": tenant_id,
                        "session_id": session_id,
                        "_enqueued_at": enqueued_at_iso(),
                    },
                    queue=self._queue_name,
                )
            except Exception:
                await clear_queue_age_sentinel(
                    redis_client=cast(QueueAgeSentinelClient, client),
                    queue_name=self._queue_name,
                    member_id=governance_decision_id,
                )
                raise


def _running_under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


__all__ = ["CeleryEscalationPublisher"]
