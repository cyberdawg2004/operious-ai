"""Celery worker application."""

from __future__ import annotations

from celery import Celery
from kombu import Queue

from app.core.config import get_settings
from app.workers.queues import (
    ALL_QUEUES,
    QUEUE_DIAGNOSTIC_NORMAL,
    QUEUE_ESCALATION,
    QUEUE_QA,
    QUEUE_SOP_INTELLIGENCE,
    QUEUE_SUPERVISOR,
    QUEUE_WEBHOOK_MAINTENANCE,
)

settings = get_settings()

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
        "reconcile_stale_escalation_outbox": {
            "queue": QUEUE_WEBHOOK_MAINTENANCE,
        },
        "cleanup_expired_webhook_nonces": {
            "queue": QUEUE_WEBHOOK_MAINTENANCE,
        },
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
    },
)


__all__ = ["celery_app"]
