"""Celery worker application."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Coroutine, Mapping
from datetime import datetime, timezone
from inspect import isawaitable
from threading import Thread
from typing import Any, TypeVar, cast

from celery import Celery
from celery.signals import task_failure, task_postrun, task_prerun, task_retry
from kombu import Queue

from app.core.config import get_settings
from app.core.redis import get_redis_client
from app.db.session import get_owner_session_factory
from app.hardening.observability.alert_evaluator import (
    get_alert_evaluator,
    initialize_alert_evaluator,
)
from app.hardening.observability.metrics_collector import (
    OperationalMetricsCollector,
    get_metrics_collector,
    initialize_metrics_collector,
)
from app.queues import (
    ALL_QUEUES,
    QUEUE_DIAGNOSTIC_NORMAL,
    QUEUE_ESCALATION,
    QUEUE_INGRESS_VOICE,
    QUEUE_QA,
    QUEUE_SOP_INTELLIGENCE,
    QUEUE_SUPERVISOR,
    QUEUE_WEBHOOK_MAINTENANCE,
)
from app.services.alert_evaluator_factory import create_alert_evaluator

settings = get_settings()
logger = logging.getLogger(__name__)
_T = TypeVar("_T")
_task_start_times: dict[str, datetime] = {}

celery_app = Celery(
    "operious",
    broker=settings.redis_url,
    backend=settings.celery_result_backend_url,
    include=[
        "app.workers.agent_tasks",
        "app.workers.escalation_recovery_tasks",
        "app.workers.escalation_tasks",
        "app.workers.execution_recovery_tasks",
        "app.workers.qa_tasks",
        "app.workers.sop_intelligence_tasks",
        "app.workers.supervisor_tasks",
        "app.workers.webhook_nonce_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_queues=[Queue(name) for name in ALL_QUEUES],
    task_default_queue=QUEUE_DIAGNOSTIC_NORMAL,
    task_routes={
        "execute_diagnostic_agent": {"queue": QUEUE_DIAGNOSTIC_NORMAL},
        "create_governance_escalation": {"queue": QUEUE_ESCALATION},
        "evaluate_session_supervisor": {"queue": QUEUE_SUPERVISOR},
        "score_supervisor_inspection": {"queue": QUEUE_QA},
        "propose_sop_intelligence_change": {"queue": QUEUE_SOP_INTELLIGENCE},
        "recover_stale_executions": {"queue": QUEUE_WEBHOOK_MAINTENANCE},
        "reconcile_stale_execution_outbox": {
            "queue": QUEUE_WEBHOOK_MAINTENANCE,
        },
        "reconcile_failed_execution_outbox": {
            "queue": QUEUE_WEBHOOK_MAINTENANCE,
        },
        "reconcile_stale_escalation_outbox": {
            "queue": QUEUE_WEBHOOK_MAINTENANCE,
        },
        "cleanup_expired_webhook_nonces": {
            "queue": QUEUE_WEBHOOK_MAINTENANCE,
        },
        "operious.workers.evaluate_alert_conditions": {
            "queue": QUEUE_WEBHOOK_MAINTENANCE,
        },
        "process_post_call_transcript": {"queue": QUEUE_INGRESS_VOICE},
    },
    task_acks_late=True,
    task_ignore_result=True,
    result_expires=settings.CELERY_RESULT_EXPIRES_SECONDS,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT_SECONDS,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT_SECONDS,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "visibility_timeout": settings.CELERY_VISIBILITY_TIMEOUT_SECONDS,
    },
    beat_schedule={
        "cleanup-expired-webhook-nonces-hourly": {
            "task": "cleanup_expired_webhook_nonces",
            "schedule": 3600.0,
            "kwargs": {"limit": 1000},
            "options": {"queue": QUEUE_WEBHOOK_MAINTENANCE},
        },
        "reconcile-stale-escalation-outbox-minutely": {
            "task": "reconcile_stale_escalation_outbox",
            "schedule": 60.0,
            "kwargs": {"limit": 100},
            "options": {"queue": QUEUE_WEBHOOK_MAINTENANCE},
        },
        "reconcile-failed-execution-outbox-minutely": {
            "task": "reconcile_failed_execution_outbox",
            "schedule": 60.0,
            "options": {"queue": QUEUE_WEBHOOK_MAINTENANCE},
        },
        "queue-depth-snapshot": {
            "task": "operious.workers.emit_queue_depth_snapshot",
            "schedule": 60.0,
            "options": {"queue": QUEUE_WEBHOOK_MAINTENANCE},
        },
        "alert-condition-evaluation": {
            "task": "operious.workers.evaluate_alert_conditions",
            "schedule": 60.0,
            "options": {"queue": QUEUE_WEBHOOK_MAINTENANCE},
        },
    },
)


def _initialize_worker_metrics_collector() -> None:
    try:
        if get_metrics_collector() is None:
            initialize_metrics_collector(OperationalMetricsCollector())
    except Exception as exc:  # noqa: BLE001 - worker metrics are best-effort.
        try:
            logger.warning(
                "worker_metrics_collector_init_failed",
                extra={"error": exc.__class__.__name__},
            )
        except Exception:
            return


_initialize_worker_metrics_collector()


def _initialize_worker_alert_evaluator() -> None:
    try:
        if get_alert_evaluator() is None:
            initialize_alert_evaluator(create_alert_evaluator())
    except Exception as exc:  # noqa: BLE001 - worker alerts are best-effort.
        try:
            logger.warning(
                "worker_alert_evaluator_init_failed",
                extra={"error": exc.__class__.__name__},
            )
        except Exception:
            return


_initialize_worker_alert_evaluator()


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="operious.workers.emit_queue_depth_snapshot",
    queue=QUEUE_WEBHOOK_MAINTENANCE,
    ignore_result=True,
)
def emit_queue_depth_snapshot() -> None:
    """PRIVILEGED_PATH: reads all queue depths and emits a log snapshot."""

    try:
        collector = get_metrics_collector()
        if collector is None:
            return
        depths = _run_async(_collect_queue_depths())
        collector.emit_queue_depth_snapshot(
            depths=depths,
            snapshot_at=_utc_now(),
        )
    except Exception as exc:  # noqa: BLE001 - metrics never fail tasks.
        _log_signal_failure(
            "queue_depth_snapshot_failed",
            error_class=exc.__class__.__name__,
        )


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="operious.workers.evaluate_alert_conditions",
    queue=QUEUE_WEBHOOK_MAINTENANCE,
    ignore_result=True,
)
def evaluate_alert_conditions() -> None:
    """Evaluate all alert conditions without crashing maintenance workers."""

    evaluator = get_alert_evaluator()
    if evaluator is None:
        logger.warning("alert_evaluator_not_initialized")
        return

    async def _run() -> None:
        # PRIVILEGED_PATH: alert evaluation reads cross-tenant maintenance state.
        async with get_owner_session_factory()() as session:
            fired = await evaluator.evaluate_all(session)
            for result in fired:
                await evaluator.fire_alert(result, session)
            logger.info(
                "alert_evaluation_complete",
                extra={
                    "conditions_evaluated": len(evaluator.CONDITIONS),
                    "alerts_fired": len(fired),
                },
            )

    try:
        asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 - alert task is best-effort.
        logger.warning(
            "alert_evaluation_failed",
            extra={"error": str(exc)},
        )


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="process_post_call_transcript",
    queue=QUEUE_INGRESS_VOICE,
    ignore_result=True,
    max_retries=1,
    default_retry_delay=30,
)
def process_post_call_transcript(call_id: str, tenant_id: str) -> None:
    """Stub hook for RT6/RT7 post-call voice work."""

    logger.info(
        "process_post_call_transcript_received",
        extra={"call_id": call_id, "tenant_id": tenant_id},
    )


@task_prerun.connect  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
def on_task_prerun(
    task_id: str | None = None,
    task: Any = None,
    args: tuple[Any, ...] | None = None,
    kwargs: dict[str, Any] | None = None,
    **_kw: Any,
) -> None:
    try:
        if task_id is None or task is None:
            return
        started_at = _utc_now()
        _task_start_times[task_id] = started_at
        collector = get_metrics_collector()
        if collector is None:
            return
        task_kwargs = kwargs or {}
        collector.emit_task_started(
            task_id=task_id,
            task_name=_task_name(task),
            queue=_queue_from_request(getattr(task, "request", None)),
            tenant_id=_tenant_id_from_args(args=args, kwargs=task_kwargs),
            enqueued_at=_parse_datetime(task_kwargs.get("_enqueued_at")),
        )
    except Exception as exc:  # noqa: BLE001 - signal handlers never raise.
        _log_signal_failure(
            "task_prerun_metrics_failed",
            task_id=task_id,
            error_class=exc.__class__.__name__,
        )


@task_postrun.connect  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
def on_task_postrun(
    task_id: str | None = None,
    task: Any = None,
    args: tuple[Any, ...] | None = None,
    kwargs: dict[str, Any] | None = None,
    retval: Any = None,
    state: str | None = None,
    **_kw: Any,
) -> None:
    del retval
    try:
        if task_id is None or task is None:
            return
        started_at = _task_start_times.pop(task_id, None)
        collector = get_metrics_collector()
        if collector is None:
            return
        collector.emit_task_completed(
            task_id=task_id,
            task_name=_task_name(task),
            queue=_queue_from_request(getattr(task, "request", None)),
            tenant_id=_tenant_id_from_args(args=args, kwargs=kwargs or {}),
            started_at=started_at,
            outcome=(state or "unknown").lower(),
        )
    except Exception as exc:  # noqa: BLE001 - signal handlers never raise.
        _log_signal_failure(
            "task_postrun_metrics_failed",
            task_id=task_id,
            error_class=exc.__class__.__name__,
        )


@task_failure.connect  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
def on_task_failure(
    task_id: str | None = None,
    exception: BaseException | None = None,
    args: tuple[Any, ...] | None = None,
    kwargs: dict[str, Any] | None = None,
    traceback: Any = None,
    einfo: Any = None,
    sender: Any = None,
    **_kw: Any,
) -> None:
    del traceback, einfo
    try:
        if task_id is None:
            return
        started_at = _task_start_times.pop(task_id, None)
        collector = get_metrics_collector()
        if collector is None:
            return
        collector.emit_task_failed(
            task_id=task_id,
            task_name=_task_name(sender),
            queue=_queue_from_request(getattr(sender, "request", None)),
            tenant_id=_tenant_id_from_args(args=args, kwargs=kwargs or {}),
            error_class=(
                exception.__class__.__name__
                if exception is not None
                else "UnknownError"
            ),
            started_at=started_at,
        )
    except Exception as exc:  # noqa: BLE001 - signal handlers never raise.
        _log_signal_failure(
            "task_failure_metrics_failed",
            task_id=task_id,
            error_class=exc.__class__.__name__,
        )


@task_retry.connect  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
def on_task_retry(
    request: Any = None,
    reason: Any = None,
    einfo: Any = None,
    **_kw: Any,
) -> None:
    del einfo
    try:
        if request is None:
            return
        collector = get_metrics_collector()
        if collector is None:
            return
        request_kwargs = _request_kwargs(request)
        collector.emit_task_retried(
            task_id=str(getattr(request, "id", "")),
            task_name=str(getattr(request, "task", "")),
            queue=_queue_from_request(request),
            tenant_id=_tenant_id_from_args(args=None, kwargs=request_kwargs),
            retry_number=int(getattr(request, "retries", 0) or 0),
            error_class=(
                reason.__class__.__name__ if reason is not None else "Retry"
            ),
        )
    except Exception as exc:  # noqa: BLE001 - signal handlers never raise.
        _log_signal_failure(
            "task_retry_metrics_failed",
            error_class=exc.__class__.__name__,
        )


def enqueued_at_iso() -> str:
    return _utc_now().isoformat()


async def _collect_queue_depths() -> dict[str, int]:
    redis_client = get_redis_client()
    depths: dict[str, int] = {}
    for queue_name in ALL_QUEUES:
        depths[queue_name] = int(
            await _resolve_depth(redis_client.llen(queue_name)) or 0
        )
    return depths


async def _resolve_depth(value: Awaitable[int] | int) -> int:
    if isawaitable(value):
        return await value
    return value


def _run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: list[_T] = []
    errors: list[BaseException] = []

    def _runner() -> None:
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = Thread(target=_runner)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    return result[0]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _as_utc(value)
    if not isinstance(value, str) or not value:
        return None
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _task_name(task: Any) -> str:
    return str(getattr(task, "name", None) or getattr(task, "task", "unknown"))


def _queue_from_request(request: Any) -> str:
    delivery_info = getattr(request, "delivery_info", None)
    if not isinstance(delivery_info, Mapping):
        return "unknown"
    info = cast(Mapping[str, object], delivery_info)
    value = info.get("routing_key")
    return str(value) if value is not None else "unknown"


def _tenant_id_from_args(
    *,
    args: tuple[Any, ...] | None,
    kwargs: Mapping[str, Any],
) -> str | None:
    tenant_id = kwargs.get("tenant_id")
    if isinstance(tenant_id, str) and tenant_id:
        return tenant_id
    if args is not None and len(args) > 1 and isinstance(args[1], str):
        return args[1]
    return None


def _request_kwargs(request: Any) -> Mapping[str, Any]:
    kwargs = getattr(request, "kwargs", None)
    if isinstance(kwargs, Mapping):
        return cast(Mapping[str, Any], kwargs)
    return {}


def _log_signal_failure(
    event_key: str,
    *,
    error_class: str,
    task_id: str | None = None,
) -> None:
    try:
        logger.warning(
            event_key,
            extra={"task_id": task_id, "error": error_class},
        )
    except Exception:
        return


__all__ = [
    "celery_app",
    "emit_queue_depth_snapshot",
    "enqueued_at_iso",
    "on_task_failure",
    "on_task_postrun",
    "on_task_prerun",
    "on_task_retry",
    "process_post_call_transcript",
]
