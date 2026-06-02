"""Queue admission compatibility tests."""

from __future__ import annotations

import logging

import pytest

from app.core.queue_admission import (
    QueueBackpressureError,
    RedisQueueDepthAdmission,
    admit_tenant_queue_publish,
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


class _TenantQoSRedis(_RedisDepth):
    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, int] = {}

    async def get(self, key: str) -> int | None:
        return self.values.get(key)

    async def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def decr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) - 1
        return self.values[key]

    async def expire(self, key: str, seconds: int) -> bool:
        del key, seconds
        return True


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
async def test_queue_depth_failure_is_logged_and_fails_closed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    admission = RedisQueueDepthAdmission(redis_client=_RedisDepth(fail=True))

    with pytest.raises(QueueBackpressureError) as exc_info:
        await admission.check(
            logical_queue="internal_execution",
            queue_name=QUEUE_DIAGNOSTIC_NORMAL,
            max_queue_depth=10,
            tenant_id="tenant-queue-admission",
            dispatch_id="dispatch-queue-admission",
        )

    assert exc_info.value.reason == "queue_depth_unavailable"
    assert "queue_depth_check_failed" in caplog.text


@pytest.mark.asyncio
async def test_tenant_qos_isolates_tenants_under_burst() -> None:
    redis = _TenantQoSRedis()

    await admit_tenant_queue_publish(
        redis_client=redis,
        logical_queue="diagnostic",
        queue_name=QUEUE_DIAGNOSTIC_NORMAL,
        tenant_id="tenant-a",
        max_tenant_depth=2,
    )
    await admit_tenant_queue_publish(
        redis_client=redis,
        logical_queue="diagnostic",
        queue_name=QUEUE_DIAGNOSTIC_NORMAL,
        tenant_id="tenant-a",
        max_tenant_depth=2,
    )
    await admit_tenant_queue_publish(
        redis_client=redis,
        logical_queue="diagnostic",
        queue_name=QUEUE_DIAGNOSTIC_NORMAL,
        tenant_id="tenant-b",
        max_tenant_depth=2,
    )
    with pytest.raises(QueueBackpressureError) as exc_info:
        await admit_tenant_queue_publish(
            redis_client=redis,
            logical_queue="diagnostic",
            queue_name=QUEUE_DIAGNOSTIC_NORMAL,
            tenant_id="tenant-a",
            max_tenant_depth=2,
        )

    assert exc_info.value.reason == "tenant_queue_backpressure"
    assert exc_info.value.tenant_id == "tenant-a"
