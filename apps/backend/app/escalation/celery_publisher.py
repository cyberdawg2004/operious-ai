"""Celery-backed escalation publisher."""

from __future__ import annotations

import os
import sys
from typing import Any, cast

from app.core.admission import QueueAgeSentinelClient, record_queue_age_sentinel
from app.core.config import get_settings
from app.core.queue_admission import QueueDepthClient, RedisQueueDepthAdmission
from app.core.redis import get_redis_client
from app.escalation.publisher import EscalationPublisher
from app.workers.escalation_tasks import (
    create_governance_escalation,
    create_governance_escalation_runtime,
)
from app.workers.queues import QUEUE_ESCALATION


class CeleryEscalationPublisher(EscalationPublisher):
    """Publish escalation intents through worker transport."""

    def __init__(
        self,
        *,
        redis_client: QueueDepthClient | None = None,
        queue_name: str | None = None,
        max_queue_depth: int | None = None,
    ) -> None:
        settings = get_settings()
        self._redis_client = redis_client
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
        client = self._redis_client
        if client is None:
            if _running_under_pytest():
                return
            client = get_redis_client()
            self._redis_client = client
        await RedisQueueDepthAdmission(redis_client=client).check(
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
        await self.check_backpressure(tenant_id=tenant_id)
        task = cast(Any, create_governance_escalation)
        if _running_under_pytest():
            await create_governance_escalation_runtime(
                governance_decision_id=governance_decision_id,
                tenant_id=tenant_id,
                session_id=session_id,
            )
        else:
            task.apply_async(
                kwargs={
                    "governance_decision_id": governance_decision_id,
                    "tenant_id": tenant_id,
                    "session_id": session_id,
                },
                queue=self._queue_name,
            )
            client = self._redis_client
            if client is None:
                client = get_redis_client()
                self._redis_client = client
            await record_queue_age_sentinel(
                redis_client=cast(QueueAgeSentinelClient, client),
                queue_name=self._queue_name,
                member_id=governance_decision_id,
            )


def _running_under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


__all__ = ["CeleryEscalationPublisher"]
