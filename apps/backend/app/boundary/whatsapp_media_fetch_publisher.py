"""Celery publisher for the B1.5 WhatsApp media fetch record.

Mirrors app.boundary.ingress_dispatch_publisher's shape: a thin
function that imports Celery lazily (this module must stay importable
from request-path code that never touches Celery directly).
"""

from __future__ import annotations

from typing import Any, cast

from app.boundary.whatsapp_media_fetch import WhatsAppMediaFetchRecord
from app.queues import QUEUE_WHATSAPP_MEDIA_FETCH


def enqueue_whatsapp_media_fetch(record: WhatsAppMediaFetchRecord) -> None:
    from app.workers.celery_app import celery_app

    cast(Any, celery_app).send_task(
        "fetch_whatsapp_media",
        kwargs={
            "fetch_id": str(record.fetch_id),
            "tenant_id": record.tenant_id,
            "attempt_number": 1,
        },
        queue=QUEUE_WHATSAPP_MEDIA_FETCH,
    )


__all__ = ["enqueue_whatsapp_media_fetch"]
