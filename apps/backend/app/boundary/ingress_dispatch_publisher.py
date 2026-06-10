"""Celery-backed publisher for durable ingress-dispatch outbox intents."""

from __future__ import annotations

from typing import Any, cast

from app.boundary.ingress_dispatch_outbox import IngressDispatchOutboxRecord
from app.queues import (
    QUEUE_INGRESS_EMAIL,
    QUEUE_INGRESS_SHOPIFY,
    QUEUE_INGRESS_WHATSAPP,
)


def enqueue_ingress_dispatch_outbox(outbox: IngressDispatchOutboxRecord) -> None:
    from app.workers.celery_app import celery_app, enqueued_at_iso

    cast(Any, celery_app).send_task(
        "dispatch_ingress",
        kwargs={
            "outbox_id": str(outbox.outbox_id),
            "_enqueued_at": enqueued_at_iso(),
        },
        queue=queue_for_ingress_dispatch_channel(outbox.channel),
    )


def queue_for_ingress_dispatch_channel(channel: str) -> str:
    if channel == "whatsapp":
        return QUEUE_INGRESS_WHATSAPP
    if channel == "shopify":
        return QUEUE_INGRESS_SHOPIFY
    return QUEUE_INGRESS_EMAIL


__all__ = [
    "enqueue_ingress_dispatch_outbox",
    "queue_for_ingress_dispatch_channel",
]
