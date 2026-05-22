"""Celery worker application."""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "operious",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.workers.agent_tasks",
        "app.workers.escalation_tasks",
        "app.workers.execution_recovery_tasks",
        "app.workers.qa_tasks",
        "app.workers.sop_intelligence_tasks",
        "app.workers.supervisor_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


__all__ = ["celery_app"]
