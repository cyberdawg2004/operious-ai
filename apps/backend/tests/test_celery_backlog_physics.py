"""Phase H Celery backlog physics coverage."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution import ExecutionRuntime, PostgresExecutionPersistence
from app.core.config import get_settings
from app.core.queue_admission import (
    RedisQueueDepthAdmission,
    QueueBackpressureError,
)
from app.core.redis_policy import verify_redis_memory_policy
from app.api.v1.schemas.health import HealthResponse
from app.escalation.celery_publisher import CeleryEscalationPublisher
from app.execution.celery_publisher import CeleryExecutionPublisher
from app.services.health_service import HealthService
from app.workers import dead_letter_persistence
from app.workers.agent_tasks import execute_diagnostic_agent
from app.workers.celery_app import celery_app
from app.workers.dead_letter_persistence import (
    PostgresDeadLetterTaskPersistence,
    derive_dead_letter_task_id,
    record_dead_letter_task,
)
from app.workers.escalation_recovery_tasks import reconcile_stale_escalation_outbox
from app.workers.escalation_tasks import create_governance_escalation
from app.workers.execution_recovery_tasks import (
    reconcile_failed_execution_outbox,
    reconcile_stale_execution_outbox,
)
from app.workers.qa_tasks import score_supervisor_inspection
from app.queues import (
    QUEUE_DIAGNOSTIC_NORMAL,
    QUEUE_ESCALATION,
    QUEUE_QA,
    QUEUE_SOP_INTELLIGENCE,
    QUEUE_SUPERVISOR,
)
from app.workers.sop_intelligence_tasks import propose_sop_intelligence_change
from app.workers.supervisor_tasks import evaluate_session_supervisor
from tests.conftest import execution_admission_token, requires_postgres


@pytest.fixture
def pg_tenant_id(request: pytest.FixtureRequest) -> str:
    if request.node.name == "test_dead_letter_task_creates_sentry_alert":
        return "tenant-phase-h"
    if request.node.name == "test_dead_letter_task_replay_is_idempotent_and_logged":
        return "tenant-phase-3"
    return "tenant-acme"


class _QueueDepthRedis:
    def __init__(self, depth: int | Mapping[str, int]) -> None:
        self.depth = depth
        self.checked_queue: str | None = None
        self.checked_queues: list[str] = []

    async def llen(self, name: str) -> int:
        self.checked_queue = name
        self.checked_queues.append(name)
        if isinstance(self.depth, Mapping):
            return self.depth.get(name, 0)
        return self.depth


class _ConfigRedis:
    def __init__(self, config: Mapping[str, Any]) -> None:
        self.config = config

    async def config_get(self, pattern: str = "*") -> Mapping[str, Any]:
        del pattern
        return self.config


async def _request_execution(
    pg_session: AsyncSession,
    *,
    tenant_id: str,
    dispatch_id: str,
    session_id: str,
):
    requested_at = datetime(2026, 5, 24, tzinfo=timezone.utc)
    runtime = ExecutionRuntime(
        persistence=PostgresExecutionPersistence(pg_session)
    )
    return await runtime.request_diagnostic_execution(
        dispatch_id=dispatch_id,
        session_id=session_id,
        tenant_id=tenant_id,
        requested_at=requested_at,
        admission_token=execution_admission_token(
            tenant_id=tenant_id,
            admitted_at=requested_at,
        ),
    )


@pytest.mark.asyncio
async def test_execution_publisher_rejects_when_queue_depth_exceeded() -> None:
    redis = _QueueDepthRedis(depth=10_001)
    publisher = CeleryExecutionPublisher(
        redis_client=redis,
        queue_name=QUEUE_DIAGNOSTIC_NORMAL,
        max_queue_depth=10_000,
    )

    with pytest.raises(QueueBackpressureError) as exc:
        await publisher.publish_execution(
            "execution-phase-h",
            tenant_id="tenant-backpressure",
        )

    assert exc.value.reason == "queue_backpressure"
    assert exc.value.queue_depth == 10_001
    assert redis.checked_queue == QUEUE_DIAGNOSTIC_NORMAL


@pytest.mark.asyncio
async def test_queue_backpressure_log_contains_operational_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    redis = _QueueDepthRedis(depth=51)
    caplog.set_level(logging.WARNING)

    with pytest.raises(QueueBackpressureError) as exc:
        await RedisQueueDepthAdmission(redis_client=redis).check(
            logical_queue="diagnostic",
            queue_name=QUEUE_DIAGNOSTIC_NORMAL,
            max_queue_depth=50,
            tenant_id="tenant-backpressure",
            dispatch_id="dispatch-backpressure",
        )

    assert exc.value.reason == "queue_backpressure"
    assert exc.value.logical_queue == "diagnostic"
    record = next(
        record
        for record in caplog.records
        if record.message == "queue_backpressure_triggered"
    )
    assert record.queue_name == QUEUE_DIAGNOSTIC_NORMAL
    assert record.current_depth == 51
    assert record.configured_limit == 50
    assert record.tenant_id == "tenant-backpressure"
    assert record.dispatch_id == "dispatch-backpressure"


@pytest.mark.asyncio
async def test_escalation_publisher_rejects_when_queue_depth_exceeded() -> None:
    redis = _QueueDepthRedis(depth=51)
    publisher = CeleryEscalationPublisher(
        redis_client=redis,
        queue_name="escalation",
        max_queue_depth=50,
    )

    with pytest.raises(QueueBackpressureError) as exc:
        await publisher.publish_governance_denial(
            governance_decision_id="decision-backpressure",
            tenant_id="tenant-backpressure",
        )

    assert exc.value.reason == "queue_backpressure"
    assert exc.value.logical_queue == "escalation"
    assert exc.value.queue_depth == 51
    assert redis.checked_queue == "escalation"


@pytest.mark.asyncio
async def test_health_report_includes_queue_depth_statuses() -> None:
    settings = get_settings().model_copy(
        update={
            "EXECUTION_QUEUE_NAME": QUEUE_DIAGNOSTIC_NORMAL,
            "EXECUTION_QUEUE_MAX_DEPTH": 100,
            "ESCALATION_QUEUE_NAME": QUEUE_ESCALATION,
            "ESCALATION_QUEUE_MAX_DEPTH": 50,
            "SUPERVISOR_QUEUE_NAME": QUEUE_SUPERVISOR,
            "SUPERVISOR_QUEUE_MAX_DEPTH": 50,
            "QA_QUEUE_NAME": QUEUE_QA,
            "QA_QUEUE_MAX_DEPTH": 50,
            "SOP_INTELLIGENCE_QUEUE_NAME": QUEUE_SOP_INTELLIGENCE,
            "SOP_INTELLIGENCE_QUEUE_MAX_DEPTH": 50,
        }
    )
    redis = _QueueDepthRedis(
        {
            QUEUE_DIAGNOSTIC_NORMAL: 0,
            QUEUE_ESCALATION: 600,
            QUEUE_SUPERVISOR: 2500,
            QUEUE_QA: 1,
            QUEUE_SOP_INTELLIGENCE: 2,
        }
    )
    service = HealthService(
        settings=settings,
        redis_provider=lambda: redis,  # type: ignore[arg-type]
    )

    report = await service.health()
    response = HealthResponse.from_report(report)

    assert response.status == "degraded"
    assert response.queues["diagnostic"].model_dump() == {
        "depth": 0,
        "limit": 2000,
        "status": "ok",
        "queue_name": QUEUE_DIAGNOSTIC_NORMAL,
        "age_seconds": None,
        "error": None,
    }
    assert response.queues["escalation"].status == "warn"
    assert response.queues["supervisor"].status == "critical"


def test_task_results_expire_within_ttl() -> None:
    settings = get_settings()

    assert celery_app.conf.result_expires == settings.CELERY_RESULT_EXPIRES_SECONDS
    assert celery_app.conf.task_soft_time_limit == (
        settings.CELERY_TASK_SOFT_TIME_LIMIT_SECONDS
    )
    assert celery_app.conf.task_time_limit == settings.CELERY_TASK_TIME_LIMIT_SECONDS
    assert settings.ESCALATION_OUTBOX_CLAIM_LEASE_SECONDS == 300
    assert settings.EXECUTION_OUTBOX_FAILED_RETRY_COOLDOWN_SECONDS == 30
    assert settings.EXECUTION_OUTBOX_FAILED_RETRY_MAX_ATTEMPTS == 3
    assert celery_app.conf.broker_transport_options == {
        "visibility_timeout": settings.CELERY_VISIBILITY_TIMEOUT_SECONDS,
    }
    assert celery_app.conf.task_ignore_result is True
    assert getattr(execute_diagnostic_agent, "ignore_result") is True
    assert getattr(evaluate_session_supervisor, "ignore_result") is True
    assert getattr(score_supervisor_inspection, "ignore_result") is True
    assert getattr(propose_sop_intelligence_change, "ignore_result") is True
    assert getattr(create_governance_escalation, "ignore_result") is True
    assert getattr(reconcile_failed_execution_outbox, "ignore_result") is True
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
    execution = await _request_execution(
        pg_session,
        tenant_id="tenant-phase-h",
        dispatch_id="dispatch-phase-h",
        session_id="session-phase-h",
    )
    execution_id = execution.execution.execution_id

    dead_letter_metadata = {
        "execution_id": str(execution_id),
        "attempt_id": "attempt-phase-h",
        "dispatch_id": "dispatch-phase-h",
        "session_id": "session-phase-h",
        "tenant_id": "tenant-phase-h",
        "attempt_count": 3,
        "error_class": "RuntimeError",
        "error_message": "diagnostic cognition failed",
        "last_traceback": "Traceback (most recent call last): RuntimeError",
        "task_payload": {
            "execution_id": "execution-phase-h",
            "attempt_id": "attempt-phase-h",
            "dispatch_id": "dispatch-phase-h",
            "session_id": "session-phase-h",
            "tenant_id": "tenant-phase-h",
        },
    }
    record = await record_dead_letter_task(
        session=pg_session,
        tenant_id="tenant-phase-h",
        task_name="execute_diagnostic_agent",
        task_id="task-phase-h",
        execution_id=execution_id,
        session_id="session-phase-h",
        attempt_count=3,
        reason="retry budget exhausted",
        retry_count=3,
        metadata=dead_letter_metadata,
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
    assert persisted.metadata["attempt_count"] == 3
    assert persisted.metadata["error_class"] == "RuntimeError"
    assert persisted.metadata["error_message"] == "diagnostic cognition failed"
    assert str(persisted.metadata["last_traceback"]).startswith("Traceback")
    assert persisted.metadata["task_payload"] == dead_letter_metadata["task_payload"]
    assert captured == [("dead_letter_task_created", "error")]


def test_dead_letter_task_id_is_deterministic_without_task_id() -> None:
    execution_id = uuid.uuid5(uuid.NAMESPACE_URL, "execution:phase-3")

    first = derive_dead_letter_task_id(
        tenant_id="tenant-phase-3",
        execution_id=execution_id,
        session_id="session-phase-3",
        attempt_count=3,
    )
    second = derive_dead_letter_task_id(
        tenant_id="tenant-phase-3",
        execution_id=execution_id,
        session_id="session-phase-3",
        attempt_count=3,
    )
    different_execution = derive_dead_letter_task_id(
        tenant_id="tenant-phase-3",
        execution_id=uuid.uuid5(uuid.NAMESPACE_URL, "execution:other"),
        session_id="session-phase-3",
        attempt_count=3,
    )
    different_attempt = derive_dead_letter_task_id(
        tenant_id="tenant-phase-3",
        execution_id=execution_id,
        session_id="session-phase-3",
        attempt_count=4,
    )

    assert second == first
    assert different_execution != first
    assert different_attempt != first


@requires_postgres
@pytest.mark.asyncio
async def test_dead_letter_task_replay_is_idempotent_and_logged(
    pg_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    captured: list[tuple[str, str | None]] = []

    def _capture_message(message: str, level: str | None = None) -> None:
        captured.append((message, level))

    monkeypatch.setattr(
        dead_letter_persistence.sentry_sdk,
        "capture_message",
        _capture_message,
    )
    caplog.set_level(logging.INFO, logger="app.workers.dead_letter_persistence")

    execution = await _request_execution(
        pg_session,
        tenant_id="tenant-phase-3",
        dispatch_id="dispatch-phase-3",
        session_id="session-phase-3",
    )
    execution_id = execution.execution.execution_id

    first = await record_dead_letter_task(
        session=pg_session,
        tenant_id="tenant-phase-3",
        task_name="execute_diagnostic_agent",
        task_id="celery-task-first",
        execution_id=execution_id,
        session_id="session-phase-3",
        attempt_count=3,
        reason="retry budget exhausted",
        retry_count=3,
        metadata={"task_payload": {"execution_id": str(execution_id)}},
    )
    await pg_session.commit()

    replay = await record_dead_letter_task(
        session=pg_session,
        tenant_id="tenant-phase-3",
        task_name="execute_diagnostic_agent",
        task_id="celery-task-replay",
        execution_id=execution_id,
        session_id="session-phase-3",
        attempt_count=3,
        reason="retry budget exhausted again",
        retry_count=3,
        metadata={"task_payload": {"execution_id": str(execution_id)}},
    )
    await pg_session.commit()

    repo = PostgresDeadLetterTaskPersistence(pg_session)
    persisted = await repo.get_dead_letter_task(
        first.dead_letter_task_id,
        expected_tenant_id="tenant-phase-3",
    )

    assert replay.dead_letter_task_id == first.dead_letter_task_id
    assert replay.task_id == "celery-task-first"
    assert persisted is not None
    assert persisted.task_id == "celery-task-first"
    assert captured == [("dead_letter_task_created", "error")]
    assert any(
        record.message == "dlq_replay_idempotent_write"
        and getattr(record, "dead_letter_task_id") == str(first.dead_letter_task_id)
        and getattr(record, "attempt_count") == 3
        for record in caplog.records
    )


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
