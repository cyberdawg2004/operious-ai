"""Trainer enqueue publication boundary."""

from __future__ import annotations

import logging
from typing import Protocol, cast

from app.queues import QUEUE_TRAINER

logger = logging.getLogger(__name__)


class _CeleryTaskPublisher(Protocol):
    def send_task(
        self,
        name: str,
        args: object | None = None,
        kwargs: dict[str, object] | None = None,
        **options: object,
    ) -> object: ...


def enqueue_trainer_for_tenant(tenant_id: str) -> bool:
    """Enqueue aggregate_qa_signals for a tenant via Celery. Returns True if enqueued."""
    try:
        from app.workers.celery_app import celery_app
        publisher = cast(_CeleryTaskPublisher, celery_app)
        publisher.send_task(
            "aggregate_qa_signals",
            kwargs={"tenant_id": tenant_id},
            queue=QUEUE_TRAINER,
        )
        return True
    except Exception:
        logger.warning("trainer_enqueue_failed tenant=%s", tenant_id, exc_info=True)
        return False


__all__ = ["enqueue_trainer_for_tenant"]
