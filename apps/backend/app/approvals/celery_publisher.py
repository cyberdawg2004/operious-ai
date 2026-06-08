"""Celery-backed approval review publisher."""

from __future__ import annotations

import os
import sys
from typing import Any, cast

from app.approvals.publisher import CaseApprovalReviewPublisher
from app.core.admission import QueueAgeSentinelClient, record_queue_age_sentinel
from app.core.redis import get_redis_client
from app.queues import QUEUE_SME_APPROVAL
from app.workers.approval_tasks import (
    review_case_approval,
    review_case_approval_runtime,
)
from app.workers.celery_app import enqueued_at_iso


class CeleryCaseApprovalReviewPublisher(CaseApprovalReviewPublisher):
    """Publish approval cases through worker transport."""

    def __init__(self, *, queue_name: str | None = None) -> None:
        self._queue_name = queue_name or QUEUE_SME_APPROVAL

    async def publish_case_review(
        self,
        *,
        approval_case_id: str,
        tenant_id: str,
    ) -> None:
        if _running_under_pytest():
            await review_case_approval_runtime(
                approval_case_id=approval_case_id,
                tenant_id=tenant_id,
            )
            return
        task = cast(Any, review_case_approval)
        task.apply_async(
            kwargs={
                "approval_case_id": approval_case_id,
                "tenant_id": tenant_id,
                "_enqueued_at": enqueued_at_iso(),
            },
            queue=self._queue_name,
        )
        await record_queue_age_sentinel(
            redis_client=cast(QueueAgeSentinelClient, get_redis_client()),
            queue_name=self._queue_name,
            member_id=approval_case_id,
        )


def _running_under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


__all__ = ["CeleryCaseApprovalReviewPublisher"]
