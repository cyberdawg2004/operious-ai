"""Celery worker application."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine, Mapping
from datetime import datetime, timezone
from threading import Thread
from typing import Any, Protocol, TypeVar, cast
from urllib.parse import urlsplit

from celery import Celery
from celery.signals import task_failure, task_postrun, task_prerun, task_retry
from kombu import Queue

from app.core.config import Settings
from app.core.config import get_settings
from app.core.queue_depth import get_queue_depth_provider
from app.core.redis import get_redis_client
from app.data_protection.crypto import DataProtectionService
from app.data_protection.kms import build_master_key_unwrap
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
    QUEUE_DEAD_LETTER,
    QUEUE_DIAGNOSTIC_NORMAL,
    QUEUE_ESCALATION,
    QUEUE_INGRESS_EMAIL,
    QUEUE_KNOWLEDGE_INDEXING,
    QUEUE_INGRESS_VOICE,
    QUEUE_OUTBOUND_SEND,
    QUEUE_QA,
    QUEUE_SOP_INTELLIGENCE,
    QUEUE_SME_APPROVAL,
    QUEUE_SUPERVISOR,
    QUEUE_WEBHOOK_MAINTENANCE,
    QUEUE_WHATSAPP_MEDIA_FETCH,
)
from app.services.crisis_events import PostgresCrisisEventRepository
from app.services.crisis_service import CrisisService

settings = get_settings()
logger = logging.getLogger(__name__)
_T = TypeVar("_T")
_task_start_times: dict[str, datetime] = {}
_VISIBILITY_TIMEOUT_BROKER_SCHEMES = {
    "redis",
    "rediss",
    "redis+socket",
    "sentinel",
    "sqs",
}


class _CeleryConfig(Protocol):
    def update(self, **kwargs: object) -> object: ...


def _broker_transport_options(settings: Settings) -> dict[str, int]:
    scheme = urlsplit(settings.celery_broker_url).scheme.lower()
    if scheme not in _VISIBILITY_TIMEOUT_BROKER_SCHEMES:
        return {}
    return {
        "visibility_timeout": settings.CELERY_VISIBILITY_TIMEOUT_SECONDS,
    }


celery_app = Celery(
    "operious",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend_url,
    include=[
        "app.workers.agent_tasks",
        "app.workers.approval_tasks",
        "app.workers.case_approval_outbox_tasks",
        "app.workers.case_approval_recovery_tasks",
        "app.workers.defect_cluster_tasks",
        "app.workers.escalation_recovery_tasks",
        "app.workers.escalation_tasks",
        "app.workers.execution_recovery_tasks",
        "app.workers.failure_pattern_tasks",
        "app.workers.ingress_dispatch_tasks",
        "app.workers.knowledge_tasks",
        "app.workers.outbound_send_tasks",
        "app.workers.outbound_tasks",
        "app.workers.qa_tasks",
        "app.workers.s10_probe_tasks",
        "app.workers.sop_intelligence_tasks",
        "app.workers.supervisor_tasks",
        "app.workers.webhook_nonce_tasks",
        "app.workers.whatsapp_media_fetch_tasks",
    ],
)

celery_conf = cast(_CeleryConfig, getattr(celery_app, "conf"))
celery_conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_queues=[Queue(name, durable=True) for name in ALL_QUEUES],
    task_default_queue=QUEUE_DIAGNOSTIC_NORMAL,
    task_routes={
        "execute_diagnostic_agent": {"queue": QUEUE_DIAGNOSTIC_NORMAL},
        "create_governance_escalation": {"queue": QUEUE_ESCALATION},
        "evaluate_session_supervisor": {"queue": QUEUE_SUPERVISOR},
        "scan_for_defect_clusters": {"queue": QUEUE_SUPERVISOR},
        "dispatch_defect_report": {"queue": QUEUE_SUPERVISOR},
        "score_supervisor_inspection": {"queue": QUEUE_QA},
        "propose_sop_intelligence_change": {"queue": QUEUE_SOP_INTELLIGENCE},
        "review_case_approval": {"queue": QUEUE_SME_APPROVAL},
        "scan_training_recommendation_gaps": {"queue": QUEUE_SOP_INTELLIGENCE},
        "detect_sop_failure_patterns": {"queue": QUEUE_SOP_INTELLIGENCE},
        "reindex_knowledge_document": {"queue": QUEUE_KNOWLEDGE_INDEXING},
        "recover_stale_executions": {"queue": QUEUE_WEBHOOK_MAINTENANCE},
        "dispatch_ingress": {"queue": QUEUE_INGRESS_EMAIL},
        "send_outbound_draft": {"queue": QUEUE_OUTBOUND_SEND},
        "fetch_whatsapp_media": {"queue": QUEUE_WHATSAPP_MEDIA_FETCH},
        "reconcile_whatsapp_media_fetch": {
            "queue": QUEUE_WHATSAPP_MEDIA_FETCH,
        },
        "reconcile_ingress_dispatch_outbox": {
            "queue": QUEUE_WEBHOOK_MAINTENANCE,
        },
        "reconcile_outbound_send_outbox": {
            "queue": QUEUE_WEBHOOK_MAINTENANCE,
        },
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
        "operious.workers.emit_queue_depth_snapshot": {
            "queue": QUEUE_WEBHOOK_MAINTENANCE,
        },
        "emit_queue_depth_snapshot": {
            "queue": QUEUE_WEBHOOK_MAINTENANCE,
        },
        "operious.workers.evaluate_alert_conditions": {
            "queue": QUEUE_WEBHOOK_MAINTENANCE,
        },
        "expire_crisis_deployments": {
            "queue": QUEUE_WEBHOOK_MAINTENANCE,
        },
        "recover_dead_letter_replays": {
            "queue": QUEUE_WEBHOOK_MAINTENANCE,
        },
        "s10_dead_letter_probe": {"queue": QUEUE_DEAD_LETTER},
        "process_post_call_transcript": {"queue": QUEUE_INGRESS_VOICE},
    },
    task_acks_late=True,
    task_ignore_result=True,
    result_expires=settings.CELERY_RESULT_EXPIRES_SECONDS,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT_SECONDS,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT_SECONDS,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_transport_options=_broker_transport_options(settings),
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
        # Requeue execution outboxes left in PUBLISHING after a publisher
        # crash so the durable execution intent is not orphaned.
        "reconcile-stale-execution-outbox-minutely": {
            "task": "reconcile_stale_execution_outbox",
            "schedule": 60.0,
            "kwargs": {"limit": 100},
            "options": {"queue": QUEUE_WEBHOOK_MAINTENANCE},
        },
        "reconcile-ingress-dispatch-outbox-minutely": {
            "task": "reconcile_ingress_dispatch_outbox",
            "schedule": 60.0,
            "kwargs": {"limit": 100},
            "options": {"queue": QUEUE_WEBHOOK_MAINTENANCE},
        },
        # Catches a whatsapp_media_fetch_records row whose initial
        # best-effort enqueue (app.services.ticket_ingress_service)
        # never reached a worker — see
        # app.workers.whatsapp_media_fetch_tasks.reconcile_whatsapp_media_fetch.
        "reconcile-whatsapp-media-fetch-minutely": {
            "task": "reconcile_whatsapp_media_fetch",
            "schedule": 60.0,
            "kwargs": {"stale_after_seconds": 600},
            "options": {"queue": QUEUE_WHATSAPP_MEDIA_FETCH},
        },
        "reconcile-outbound-send-outbox-minutely": {
            "task": "reconcile_outbound_send_outbox",
            "schedule": 60.0,
            "kwargs": {"limit": 100},
            "options": {"queue": QUEUE_WEBHOOK_MAINTENANCE},
        },
        "reconcile-failed-execution-outbox-minutely": {
            "task": "reconcile_failed_execution_outbox",
            "schedule": 60.0,
            "options": {"queue": QUEUE_WEBHOOK_MAINTENANCE},
        },
        # Catches a PENDING execution outbox row that reconcile-failed-
        # execution-outbox already reset once but nothing ever
        # re-attempted -- see
        # ExecutionRuntime.reconcile_stuck_pending_outbox_records.
        "reconcile-stuck-pending-execution-outbox-minutely": {
            "task": "reconcile_stuck_pending_execution_outbox",
            "schedule": 60.0,
            "options": {"queue": QUEUE_WEBHOOK_MAINTENANCE},
        },
        # Catches a case_approval_records row left in awaiting_approval
        # after its bound action already resolved — see
        # app.workers.case_approval_recovery_tasks for why the inline
        # approve_case/reject_case path can diverge from the case's own
        # status update.
        "reconcile-stale-case-approvals-minutely": {
            "task": "reconcile_stale_case_approvals",
            "schedule": 60.0,
            "kwargs": {"limit": 100},
            "options": {"queue": QUEUE_WEBHOOK_MAINTENANCE},
        },
        # Drains case_approval_outbox: a row is written every time a case
        # finishes SME review and enters awaiting_approval (see
        # app.services.case_approval_service.review_case) but nothing
        # consumed those rows before this task -- see
        # app.workers.case_approval_outbox_tasks for the publish/skip
        # logic.
        "publish-case-approval-outbox-minutely": {
            "task": "publish_case_approval_outbox",
            "schedule": 60.0,
            "kwargs": {"limit": 100},
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
        "scan-defect-clusters-quarter-hourly": {
            "task": "scan_for_defect_clusters",
            "schedule": 900.0,
            "options": {"queue": QUEUE_SUPERVISOR},
        },
        "expire-crisis-deployments-minutely": {
            "task": "expire_crisis_deployments",
            "schedule": 60.0,
            "kwargs": {"limit": 100},
            "options": {"queue": QUEUE_WEBHOOK_MAINTENANCE},
        },
        "scan-training-recommendation-gaps-daily": {
            "task": "scan_training_recommendation_gaps",
            "schedule": float(settings.SOP_REPEATED_FAILURE_SCAN_SECONDS),
            "options": {"queue": QUEUE_SOP_INTELLIGENCE},
        },
        "detect-sop-failure-patterns-every-two-hours": {
            "task": "detect_sop_failure_patterns",
            "schedule": 7200.0,
            "options": {"queue": QUEUE_SOP_INTELLIGENCE},
        },
        # Enforce per-tenant data-retention policy by crypto-shredding cognition
        # audit data past its window (#56). Daily is sufficient for day-grained
        # retention; legal holds are respected by the service.
        "purge-expired-protected-data-daily": {
            "task": "purge_expired_protected_data",
            "schedule": 86400.0,
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
    # Imported lazily: app.services.alert_evaluator_factory transitively
    # imports app.runtime, which imports app.workers.escalation_tasks, which
    # imports celery_app from this module. A top-level import here would be
    # circular (this module's `celery_app` isn't defined yet during its own
    # import). By the time this function runs, the module is fully loaded.
    from app.services.alert_evaluator_factory import create_alert_evaluator

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


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="operious.workers.emit_queue_depth_snapshot",
    queue=QUEUE_WEBHOOK_MAINTENANCE,
    ignore_result=True,
    # No retry: metric snapshot, next beat run covers any miss.
    max_retries=0,
    default_retry_delay=0,
)
def emit_queue_depth_snapshot() -> None:
    """PRIVILEGED_PATH: reads all queue depths and emits a log snapshot."""

    # DLQ: intentionally omitted for periodic beat tasks. Failure impact is
    # one missed execution; the next scheduled run covers the gap. No replay
    # needed.
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
    # No retry: periodic beat task, will re-run on next schedule.
    max_retries=0,
    default_retry_delay=0,
)
def evaluate_alert_conditions() -> None:
    """Evaluate all alert conditions without crashing maintenance workers."""

    # DLQ: intentionally omitted for periodic beat tasks. Failure impact is
    # one missed execution; the next scheduled run covers the gap. No replay
    # needed.
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
    name="expire_crisis_deployments",
    queue=QUEUE_WEBHOOK_MAINTENANCE,
    ignore_result=True,
    max_retries=1,
    default_retry_delay=60,
)
def expire_crisis_deployments(limit: int = 100) -> None:
    """PRIVILEGED_PATH: mark expired crisis deployments across tenants."""

    # DLQ: intentionally omitted for periodic beat tasks. Failure impact is
    # one missed execution; the next scheduled run covers the gap. No replay
    # needed.
    async def _run() -> None:
        async with get_owner_session_factory()() as session:
            expired = await CrisisService(
                session=session,
                redis_client=get_redis_client(),
                event_repository=PostgresCrisisEventRepository(session),
            ).expire_due(limit=limit)
            logger.info(
                "crisis_deployments_expired",
                extra={"count": expired},
            )

    try:
        _run_async(_run())
    except Exception as exc:  # noqa: BLE001 - maintenance task must not crash worker.
        logger.warning(
            "crisis_deployments_expiry_failed",
            extra={"error": str(exc)},
        )


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="purge_expired_protected_data",
    queue=QUEUE_WEBHOOK_MAINTENANCE,
    ignore_result=True,
    max_retries=1,
    default_retry_delay=60,
)
def purge_expired_protected_data() -> None:
    """PRIVILEGED_PATH: crypto-shred cognition audit data past each tenant's
    retention window (#56).

    Enforces the per-tenant data-retention policy automatically. Without this
    scheduled run, ``purge_expired_cognition_audits`` would never execute and
    retention would be policy-on-paper only. Legal holds are respected inside
    the service (held tenants are skipped).
    """

    # DLQ intentionally omitted (periodic beat task): a missed run is covered
    # by the next scheduled run; no replay needed.
    async def _run() -> None:
        async with get_owner_session_factory()() as session:
            service = DataProtectionService.from_settings(
                session,
                settings,
                master_key_unwrap=build_master_key_unwrap(settings),
                legacy_credential_key=settings.TENANT_CREDENTIAL_MASTER_KEY,
            )
            purged = await service.purge_expired_cognition_audits()
            await session.commit()
            logger.info(
                "data_protection_retention_purged",
                extra={"count": purged},
            )

    try:
        _run_async(_run())
    except Exception as exc:  # noqa: BLE001 - maintenance task must not crash worker.
        logger.warning(
            "data_protection_retention_purge_failed",
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
            error_class=(reason.__class__.__name__ if reason is not None else "Retry"),
        )
    except Exception as exc:  # noqa: BLE001 - signal handlers never raise.
        _log_signal_failure(
            "task_retry_metrics_failed",
            error_class=exc.__class__.__name__,
        )


def enqueued_at_iso() -> str:
    return _utc_now().isoformat()


# Deferred until enqueued_at_iso (and celery_app) are defined: the alert
# evaluator factory transitively imports app.workers.escalation_tasks, which
# imports both `celery_app` and `enqueued_at_iso` from this module.
_initialize_worker_alert_evaluator()


async def _collect_queue_depths() -> dict[str, int]:
    """Sample every queue's depth, isolating one queue's failure from the rest.

    One unreachable queue (e.g. a 404 for a queue never created on the
    broker) must not discard every other queue's already-fetched depth.
    A failed queue is omitted from the result rather than reported as 0
    or any other placeholder -- "unknown" must never read as "empty" or
    "huge" to a consumer (including admission telemetry), so it is simply
    absent.
    """

    queue_depth_provider = get_queue_depth_provider()
    depths: dict[str, int] = {}
    for queue_name in ALL_QUEUES:
        try:
            depths[queue_name] = (
                await queue_depth_provider.get_queue_depth(queue_name)
            ).depth
        except Exception as exc:  # noqa: BLE001 - one queue's outage must not abort the snapshot.
            logger.warning(
                "queue_depth_snapshot_queue_failed",
                extra={"queue_name": queue_name, "error": exc.__class__.__name__},
            )
    return depths


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
