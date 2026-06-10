"""Celery publisher for governed outbound send outbox rows."""

from __future__ import annotations

from typing import Any, cast

from app.boundary.outbound.send_outbox import OutboundSendOutboxRecord
from app.queues import QUEUE_OUTBOUND_SEND


def queue_for_outbound_send_channel(_channel: str) -> str:
    """Return the queue used for governed customer reply sends."""

    return QUEUE_OUTBOUND_SEND


def enqueue_outbound_send_outbox(outbox: OutboundSendOutboxRecord) -> None:
    """Enqueue a durable outbound send intent by id."""

    from app.workers.celery_app import celery_app, enqueued_at_iso

    cast(Any, celery_app).send_task(
        "send_outbound_draft",
        kwargs={
            "outbox_id": str(outbox.outbox_id),
            "_enqueued_at": enqueued_at_iso(),
        },
        queue=queue_for_outbound_send_channel(outbox.channel),
    )


__all__ = [
    "enqueue_outbound_send_outbox",
    "queue_for_outbound_send_channel",
]
