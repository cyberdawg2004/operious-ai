"""Celery-backed publisher for frozen semantic quarantine notifications."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from app.queues import QUEUE_SEMANTIC_QUARANTINE


class CelerySemanticQuarantinePublisher:
    """Publish to the frozen semantic quarantine queue."""

    def publish(
        self,
        *,
        quarantine_id: str,
        tenant_id: str,
        payload: Mapping[str, Any],
    ) -> None:
        from app.workers.celery_app import celery_app

        cast(Any, celery_app).send_task(
            "semantic_quarantine.frozen",
            kwargs={
                "quarantine_id": quarantine_id,
                "tenant_id": tenant_id,
                "payload": dict(payload),
            },
            queue=QUEUE_SEMANTIC_QUARANTINE,
        )


__all__ = ["CelerySemanticQuarantinePublisher"]
