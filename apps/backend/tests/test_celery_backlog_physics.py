"""Phase H Celery backlog physics coverage."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis_policy import verify_redis_memory_policy
from app.execution.celery_publisher import CeleryExecutionPublisher
from app.execution.publisher import QueueBackpressureError
from app.workers import dead_letter_persistence
from app.workers.celery_app import celery_app
from app.workers.dead_letter_persistence import (
    PostgresDeadLetterTaskPersistence,
    record_dead_letter_task,
)
from app.workers.escalation_recovery_tasks import reconcile_stale_escalation_outbox
from app.workers.escalation_tasks import create_governance_escalation
from app.workers.execution_recovery_tasks import reconcile_stale_execution_outbox
from app.workers.qa_tasks import score_supervisor_inspection
from app.workers.sop_intelligence_tasks import propose_sop_intelligence_change
from app.workers.supervisor_tasks import evaluate_session_supervisor
from tests.conftest import requires_postgres


class _QueueDepthRedis:
    def __init__(self, depth: int) -> None:
        self.depth = depth
        self.checked_queue: str | None = None

    async def llen(self, name: str) -> int:
        self.checked_queue = name
        return self.depth


class _ConfigRedis:
    def __init__(self, config: Mapping[str, Any]) -> None:
        self.config = config

    async def config_get(self, pattern: str = "*") -> Mapping[str, Any]:
        del pattern
        return self.config


@pytest.mark.asyncio
async def test_execution_publisher_rejects_when_queue_depth_exceeded() -> None:
    redis = _QueueDepthRedis(depth=10_001)
    publisher = CeleryExecutionPublisher(
        redis_client=redis,
        queue_name="celery",
        max_queue_depth=10_000,
    )

    with pytest.raises(QueueBackpressureError) as exc:
        await publisher.publish_execution("execution-phase-h")

    assert exc.value.reason == "queue_backpressure"
    assert exc.value.queue_depth == 10_001
    assert redis.checked_queue == "celery"


def test_task_results_expire_within_ttl() -> None:
    settings = get_settings()

    assert celery_app.conf.result_expires == settings.CELERY_RESULT_EXPIRES_SECONDS
    assert celery_app.conf.task_soft_time_limit == (
        settings.CELERY_TASK_SOFT_TIME_LIMIT_SECONDS
    )
    assert celery_app.conf.task_time_limit == settings.CELERY_TASK_TIME_LIMIT_SECONDS
    assert celery_app.conf.broker_transport_options == {
        "visibility_timeout": settings.CELERY_VISIBILITY_TIMEOUT_SECONDS,
    }
    assert celery_app.conf.task_ignore_result is False
    assert getattr(evaluate_session_supervisor, "ignore_result") is True
    assert getattr(score_supervisor_inspection, "ignore_result") is True
    assert getattr(propose_sop_intelligence_change, "ignore_result") is True
    assert getattr(create_governance_escalation, "ignore_result") is True
    assert getattr(reconcile_stale_execution_outbox, "ignore_result") is True
    assert getattr(reconcile_stale_escalation_outbox, "ignore_result") is True


@requires_postgres
@pytest.mark.asyncio
async def test_dead_letter_task_creates_sentry_alert(
    pg_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[str, str | None]] = []

    def _capture_message(message: str, level: str | None = None) -> None:
        captured.append((message, level))

    monkeypatch.setattr(
        dead_letter_persistence.sentry_sdk,
        "capture_message",
        _capture_message,
    )

    record = await record_dead_letter_task(
        session=pg_session,
        tenant_id="tenant-phase-h",
        task_name="execute_diagnostic_agent",
        task_id="task-phase-h",
        reason="retry budget exhausted",
        retry_count=3,
        metadata={"phase": "h"},
    )
    await pg_session.commit()

    repo = PostgresDeadLetterTaskPersistence(pg_session)
    persisted = await repo.get_dead_letter_task(
        record.dead_letter_task_id,
        expected_tenant_id="tenant-phase-h",
    )

    assert persisted is not None
    assert persisted.reason == "retry budget exhausted"
    assert persisted.retry_count == 3
    assert persisted.metadata["phase"] == "h"
    assert captured == [("dead_letter_task_created", "error")]


@pytest.mark.asyncio
async def test_redis_memory_policy_check_warns_on_misconfiguration(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)

    result = await verify_redis_memory_policy(
        redis_client=_ConfigRedis({"maxmemory-policy": "noeviction"}),
        expected_policy="allkeys-lru",
    )

    assert result.valid is False
    assert result.reason == "policy_mismatch"
    assert result.observed_policy == "noeviction"
    assert "redis_memory_policy_misconfigured" in caplog.text
