"""Operational metrics collector tests for PR_T6."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import pytest

from app.api.v1.schemas.health import HealthResponse
from app.core.config import get_settings
from app.execution import celery_publisher as execution_publisher_module
from app.execution.celery_publisher import CeleryExecutionPublisher
from app.hardening.observability import metrics_collector as collector_module
from app.hardening.observability.metrics_collector import (
    OperationalMetricsCollector,
    get_metrics_collector,
    initialize_metrics_collector,
)
from app.queues import (
    ALL_QUEUES,
    QUEUE_DIAGNOSTIC_HIGH,
    QUEUE_DIAGNOSTIC_NORMAL,
    QUEUE_DIAGNOSTIC_RETRY,
)
from app.services.health_service import HealthService
from app.workers import celery_app as celery_app_module


def test_emit_task_started_fields(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    enqueued_at = datetime.now(timezone.utc) - timedelta(seconds=2)

    OperationalMetricsCollector().emit_task_started(
        task_id="task-1",
        task_name="execute_diagnostic_agent",
        queue=QUEUE_DIAGNOSTIC_NORMAL,
        tenant_id="tenant-acme",
        enqueued_at=enqueued_at,
    )

    record = _record(caplog, "task.started")
    assert record.task_id == "task-1"
    assert record.task_name == "execute_diagnostic_agent"
    assert record.queue == QUEUE_DIAGNOSTIC_NORMAL
    assert record.tenant_id == "tenant-acme"
    assert record.queue_wait_ms >= 0


def test_emit_task_completed_calculates_duration(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    started_at = datetime.now(timezone.utc) - timedelta(milliseconds=25)

    OperationalMetricsCollector().emit_task_completed(
        task_id="task-2",
        task_name="execute_diagnostic_agent",
        queue=QUEUE_DIAGNOSTIC_NORMAL,
        tenant_id="tenant-acme",
        started_at=started_at,
        outcome="success",
    )

    record = _record(caplog, "task.completed")
    assert record.task_id == "task-2"
    assert record.outcome == "success"
    assert record.processing_duration_ms >= 0


def test_emit_admission_decision_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    OperationalMetricsCollector().emit_admission_decision(
        tenant_id="tenant-acme",
        channel="email",
        decision="DEFER",
        queue_name=QUEUE_DIAGNOSTIC_NORMAL,
        reason="QUEUE_DEPTH_EXCEEDED",
        admission_telemetry_unavailable=True,
        channel_class="async_ticket",
        unavailable_reasons=("queue_depth_unavailable:diagnostic",),
        final_decision="DEFER",
    )

    record = _record(caplog, "admission.decision")
    assert record.tenant_id == "tenant-acme"
    assert record.channel == "email"
    assert record.decision == "DEFER"
    assert record.queue_name == QUEUE_DIAGNOSTIC_NORMAL
    assert record.reason == "QUEUE_DEPTH_EXCEEDED"
    assert record.admission_telemetry_unavailable is True
    assert record.channel_class == "async_ticket"
    assert record.unavailable_reasons == ("queue_depth_unavailable:diagnostic",)
    assert record.final_decision == "DEFER"


def test_emit_queue_depth_snapshot_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    snapshot_at = datetime.now(timezone.utc)

    OperationalMetricsCollector().emit_queue_depth_snapshot(
        depths={QUEUE_DIAGNOSTIC_NORMAL: 3},
        snapshot_at=snapshot_at,
    )

    record = _record(caplog, "queue.depth_snapshot")
    assert record.depths == {QUEUE_DIAGNOSTIC_NORMAL: 3}
    assert record.snapshot_at == snapshot_at.isoformat()


def test_emit_does_not_raise_on_logger_failure() -> None:
    class _FailingLogger:
        def info(self, msg: str, *args: object, **kwargs: object) -> None:
            del msg, args, kwargs
            raise RuntimeError("logger failed")

        def warning(self, msg: str, *args: object, **kwargs: object) -> None:
            del msg, args, kwargs
            raise RuntimeError("warning failed")

    OperationalMetricsCollector(logger=_FailingLogger()).emit_task_retried(
        task_id="task-3",
        task_name="execute_diagnostic_agent",
        queue=QUEUE_DIAGNOSTIC_RETRY,
        tenant_id="tenant-acme",
        retry_number=1,
        error_class="ProviderRateLimitError",
    )


def test_collector_returns_none_before_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(collector_module, "_collector", None)

    assert get_metrics_collector() is None


def test_collector_returns_instance_after_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(collector_module, "_collector", None)
    collector = OperationalMetricsCollector()

    initialize_metrics_collector(collector)

    assert get_metrics_collector() is collector


@pytest.mark.asyncio
async def test_health_returns_all_14_queues() -> None:
    response = await _health_response(_MetricsRedis())

    assert set(ALL_QUEUES).issubset(response.queues)
    assert len(ALL_QUEUES) == 14
    assert response.queues[QUEUE_DIAGNOSTIC_NORMAL].status == "ok"


@pytest.mark.asyncio
async def test_health_returns_unknown_status_when_redis_down() -> None:
    response = await _health_response(_MetricsRedis(fail_llen=True))

    for queue_name in ALL_QUEUES:
        queue = response.queues[queue_name]
        assert queue.depth == 0
        assert queue.status == "unknown"
        assert queue.error == "redis_unavailable"


@pytest.mark.asyncio
async def test_health_queue_status_thresholds() -> None:
    response = await _health_response(
        _MetricsRedis(
            depths={
                QUEUE_DIAGNOSTIC_HIGH: 0,
                QUEUE_DIAGNOSTIC_NORMAL: 600,
                QUEUE_DIAGNOSTIC_RETRY: 2500,
            }
        )
    )

    assert response.queues[QUEUE_DIAGNOSTIC_HIGH].status == "ok"
    assert response.queues[QUEUE_DIAGNOSTIC_NORMAL].status == "warn"
    assert response.queues[QUEUE_DIAGNOSTIC_RETRY].status == "critical"


@pytest.mark.asyncio
async def test_health_queue_age_timeout_does_not_block_depths() -> None:
    redis = _MetricsRedis(hang_zrange=True)
    settings = get_settings().model_copy(
        update={
            "ADMISSION_QUEUE_DEPTH_WARN": 500,
            "ADMISSION_QUEUE_DEPTH_REJECT": 2000,
            "SURVIVABILITY_READINESS_PROBE_TIMEOUT_SECONDS": 0.2,
        }
    )
    service = HealthService(
        settings=settings,
        redis_provider=lambda: redis,  # type: ignore[arg-type]
    )

    started = asyncio.get_running_loop().time()
    response = HealthResponse.from_report(await service.health())
    elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < 1.0
    assert set(ALL_QUEUES).issubset(response.queues)
    assert response.queues[QUEUE_DIAGNOSTIC_NORMAL].status == "ok"
    assert response.queues[QUEUE_DIAGNOSTIC_NORMAL].age_seconds is None


@pytest.mark.asyncio
async def test_health_collects_queue_depths_concurrently() -> None:
    redis = _MetricsRedis(delay_llen_seconds=0.1)
    settings = get_settings().model_copy(
        update={
            "ADMISSION_QUEUE_DEPTH_WARN": 500,
            "ADMISSION_QUEUE_DEPTH_REJECT": 2000,
            "SURVIVABILITY_READINESS_PROBE_TIMEOUT_SECONDS": 0.5,
        }
    )
    service = HealthService(
        settings=settings,
        redis_provider=lambda: redis,  # type: ignore[arg-type]
    )

    started = asyncio.get_running_loop().time()
    response = HealthResponse.from_report(await service.health())
    elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < 1.0
    assert set(ALL_QUEUES).issubset(response.queues)
    assert all(response.queues[name].status == "ok" for name in ALL_QUEUES)


@pytest.mark.asyncio
async def test_enqueued_at_injected_into_task_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _MetricsRedis()
    task = _FakeTask()
    monkeypatch.setattr(
        execution_publisher_module,
        "_running_under_pytest",
        lambda: False,
    )
    monkeypatch.setattr(
        execution_publisher_module,
        "execute_diagnostic_agent",
        task,
    )
    publisher = CeleryExecutionPublisher(
        redis_client=redis,  # type: ignore[arg-type]
        queue_name=QUEUE_DIAGNOSTIC_NORMAL,
        max_queue_depth=100,
        run_inline_under_pytest=False,
    )

    await publisher.publish_execution(
        "execution-metrics",
        tenant_id="tenant-acme",
    )

    kwargs = task.calls[0]["kwargs"]
    assert isinstance(kwargs, dict)
    assert isinstance(kwargs["_enqueued_at"], str)
    assert datetime.fromisoformat(kwargs["_enqueued_at"])


def test_task_prerun_signal_swallows_collector_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(collector_module, "_collector", _RaisingCollector())

    celery_app_module.on_task_prerun(
        task_id="task-prerun",
        task=_FakeSignalTask(),
        args=("execution-1", "tenant-acme"),
        kwargs={"_enqueued_at": datetime.now(timezone.utc).isoformat()},
    )


def test_task_postrun_signal_swallows_collector_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(collector_module, "_collector", _RaisingCollector())
    celery_app_module._task_start_times["task-postrun"] = datetime.now(  # pyright: ignore[reportPrivateUsage]
        timezone.utc
    )

    celery_app_module.on_task_postrun(
        task_id="task-postrun",
        task=_FakeSignalTask(),
        args=("execution-1", "tenant-acme"),
        kwargs={},
        retval=None,
        state="SUCCESS",
    )

    assert "task-postrun" not in celery_app_module._task_start_times  # pyright: ignore[reportPrivateUsage]


async def _health_response(redis: "_MetricsRedis") -> HealthResponse:
    settings = get_settings().model_copy(
        update={
            "ADMISSION_QUEUE_DEPTH_WARN": 500,
            "ADMISSION_QUEUE_DEPTH_REJECT": 2000,
        }
    )
    service = HealthService(
        settings=settings,
        redis_provider=lambda: redis,  # type: ignore[arg-type]
    )
    return HealthResponse.from_report(await service.health())


def _record(caplog: pytest.LogCaptureFixture, message: str) -> logging.LogRecord:
    return next(record for record in caplog.records if record.message == message)


class _MetricsRedis:
    def __init__(
        self,
        depths: Mapping[str, int] | None = None,
        *,
        fail_llen: bool = False,
        hang_zrange: bool = False,
        delay_llen_seconds: float = 0.0,
    ) -> None:
        self.depths = dict(depths or {})
        self.fail_llen = fail_llen
        self.hang_zrange = hang_zrange
        self.delay_llen_seconds = delay_llen_seconds
        self.zadds: list[tuple[str, Mapping[str, float], bool]] = []

    async def llen(self, name: str) -> int:
        if self.delay_llen_seconds:
            await asyncio.sleep(self.delay_llen_seconds)
        if self.fail_llen:
            raise RuntimeError("redis unavailable")
        return self.depths.get(name, 0)

    async def zrange(
        self,
        name: str,
        start: int,
        end: int,
        *,
        withscores: bool = False,
    ) -> list[tuple[str, float]]:
        del name, start, end, withscores
        if self.hang_zrange:
            await asyncio.sleep(10)
        return []

    async def zadd(
        self,
        name: str,
        mapping: Mapping[str, float],
        *,
        nx: bool = False,
    ) -> int:
        self.zadds.append((name, mapping, nx))
        return 1

    async def info(self, section: str | None = None) -> Mapping[str, Any]:
        del section
        return {"used_memory": 1, "maxmemory": 0}


class _FakeTask:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def apply_async(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


class _FakeRequest:
    delivery_info = {"routing_key": QUEUE_DIAGNOSTIC_NORMAL}


class _FakeSignalTask:
    name = "execute_diagnostic_agent"
    request = _FakeRequest()


class _RaisingCollector:
    def emit_task_started(self, **kwargs: object) -> None:
        del kwargs
        raise RuntimeError("collector failed")

    def emit_task_completed(self, **kwargs: object) -> None:
        del kwargs
        raise RuntimeError("collector failed")
