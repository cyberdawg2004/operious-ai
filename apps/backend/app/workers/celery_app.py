"""Celery worker application."""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

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
    task_acks_late=True,
    task_ignore_result=False,
    result_expires=settings.CELERY_RESULT_EXPIRES_SECONDS,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT_SECONDS,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT_SECONDS,
    worker_prefetch_multiplier=1,
    broker_transport_options={
        "visibility_timeout": settings.CELERY_VISIBILITY_TIMEOUT_SECONDS,
    },
    beat_schedule={
        "cleanup-expired-webhook-nonces-hourly": {
            "task": "cleanup_expired_webhook_nonces",
            "schedule": 3600.0,
            "kwargs": {"limit": 1000},
        },
        "reconcile-stale-escalation-outbox-minutely": {
            "task": "reconcile_stale_escalation_outbox",
            "schedule": 60.0,
            "kwargs": {"limit": 100},
        },
    },
)


__all__ = ["celery_app"]
