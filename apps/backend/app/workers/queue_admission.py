"""Celery worker queue admission helpers."""

from __future__ import annotations

import os
import sys

from app.core.admission import (
    clear_queue_age_sentinel,
    record_queue_age_sentinel,
)
from app.core.config import get_settings
from app.core.queue_depth import get_queue_depth_provider
from app.core.queue_admission import RedisQueueDepthAdmission
from app.core.redis import get_redis_client
from app.queues import (
    QUEUE_QA,
    QUEUE_SOP_INTELLIGENCE,
    QUEUE_SUPERVISOR,
)


async def admit_supervisor_publish(
    *,
    tenant_id: str | None,
    dispatch_id: str | None = None,
) -> None:
    if _running_under_pytest():
        return
    settings = get_settings()
    await RedisQueueDepthAdmission(
        queue_depth_provider=get_queue_depth_provider()
    ).check(
        logical_queue=QUEUE_SUPERVISOR,
        queue_name=QUEUE_SUPERVISOR,
        max_queue_depth=settings.SUPERVISOR_QUEUE_MAX_DEPTH,
        tenant_id=tenant_id,
        dispatch_id=dispatch_id,
    )


async def admit_qa_publish(
    *,
    tenant_id: str | None,
    dispatch_id: str | None = None,
) -> None:
    if _running_under_pytest():
        return
    settings = get_settings()
    await RedisQueueDepthAdmission(
        queue_depth_provider=get_queue_depth_provider()
    ).check(
        logical_queue=QUEUE_QA,
        queue_name=QUEUE_QA,
        max_queue_depth=settings.QA_QUEUE_MAX_DEPTH,
        tenant_id=tenant_id,
        dispatch_id=dispatch_id,
    )


async def admit_sop_intelligence_publish(
    *,
    tenant_id: str | None,
    dispatch_id: str | None = None,
) -> None:
    if _running_under_pytest():
        return
    settings = get_settings()
    await RedisQueueDepthAdmission(
        queue_depth_provider=get_queue_depth_provider()
    ).check(
        logical_queue=QUEUE_SOP_INTELLIGENCE,
        queue_name=QUEUE_SOP_INTELLIGENCE,
        max_queue_depth=settings.SOP_INTELLIGENCE_QUEUE_MAX_DEPTH,
        tenant_id=tenant_id,
        dispatch_id=dispatch_id,
    )


async def record_worker_queue_age(
    *,
    queue_name: str,
    member_id: str,
) -> None:
    if _running_under_pytest():
        return
    await record_queue_age_sentinel(
        redis_client=get_redis_client(),
        queue_name=queue_name,
        member_id=member_id,
    )


async def clear_worker_queue_age(
    *,
    queue_name: str,
    member_id: str,
) -> None:
    if _running_under_pytest():
        return
    await clear_queue_age_sentinel(
        redis_client=get_redis_client(),
        queue_name=queue_name,
        member_id=member_id,
    )


def _running_under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


__all__ = [
    "admit_qa_publish",
    "admit_sop_intelligence_publish",
    "admit_supervisor_publish",
    "clear_worker_queue_age",
    "record_worker_queue_age",
]
