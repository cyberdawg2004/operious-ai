"""Queue admission compatibility tests."""

from __future__ import annotations

import logging

import pytest

from app.core.queue_admission import (
    QueueBackpressureError,
    RedisQueueDepthAdmission,
)
from app.queues import QUEUE_DIAGNOSTIC_NORMAL


class _RedisDepth:
    def __init__(self, *, depth: int = 0, fail: bool = False) -> None:
        self.depth = depth
        self.fail = fail

    async def llen(self, name: str) -> int:
        del name
        if self.fail:
            raise RuntimeError("redis unavailable")
        return self.depth


@pytest.mark.asyncio
async def test_queue_depth_threshold_behavior_is_unchanged() -> None:
    admission = RedisQueueDepthAdmission(redis_client=_RedisDepth(depth=11))

    with pytest.raises(QueueBackpressureError):
        await admission.check(
            logical_queue="diagnostic",
            queue_name=QUEUE_DIAGNOSTIC_NORMAL,
            max_queue_depth=10,
            tenant_id="tenant-queue-admission",
            dispatch_id="dispatch-queue-admission",
        )


@pytest.mark.asyncio
async def test_queue_depth_failure_remains_logged_fail_open(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    admission = RedisQueueDepthAdmission(redis_client=_RedisDepth(fail=True))

    await admission.check(
        logical_queue="internal_execution",
        queue_name=QUEUE_DIAGNOSTIC_NORMAL,
        max_queue_depth=10,
        tenant_id="tenant-queue-admission",
        dispatch_id="dispatch-queue-admission",
    )

    assert "queue_depth_check_failed" in caplog.text
