"""`ZendeskWebhookAdapter` — reference normalisation example.

Maps a minimal Zendesk-shaped webhook into the canonical
`BoundaryNormalizationResult` vocabulary.

Expected payload shape (one of):

* ``{"event_id": "...", "ticket_id": "...", "type": "ticket.created", ...}``
* ``{"event_id": "...", "ticket_id": "...", "type": "ticket.updated", ...}``
* ``{"event_id": "...", "ticket_id": "...", "type": "ticket.comment_created", ...}``

The adapter does NOT verify Zendesk's signature scheme — that
belongs in production subclasses with the actual signing secret
configured. It DOES classify message types into the canonical
`BoundaryMessageType` vocabulary.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from app.boundary.adapters.base import BaseIngressAdapter
from app.boundary.enums import (
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundarySourceType,
)
from app.boundary.exceptions import (
    BoundaryNormalizationError,
)
from app.boundary.models.normalization import (
    BoundaryNormalizationResult,
)
from app.boundary.models.payload import IngressPayload
from app.boundary.models.source import BoundarySource


_ZENDESK_TYPE_MAP: dict[str, BoundaryMessageType] = {
    "ticket.created": BoundaryMessageType.EVENT_CREATED,
    "ticket.updated": BoundaryMessageType.EVENT_UPDATED,
    "ticket.comment_created": BoundaryMessageType.MESSAGE_RECEIVED,
    "ticket.status_changed": BoundaryMessageType.STATUS_UPDATE,
}


class ZendeskWebhookAdapter(BaseIngressAdapter):
    """Reference Zendesk webhook adapter."""

    DEFAULT_NAME = "zendesk_webhook_adapter"

    def __init__(self, *, name: str | None = None) -> None:
        super().__init__(
            name=name or self.DEFAULT_NAME,
            source_type=BoundarySourceType.ZENDESK,
        )

    def normalize(
        self,
        *,
        source: BoundarySource,
        payload: IngressPayload,
    ) -> BoundaryNormalizationResult:
        body = payload.body
        if not isinstance(body, Mapping):
            raise BoundaryNormalizationError(
                "Zendesk payload must be a mapping"
            )
        event_id = body.get("event_id") or body.get("id")
        ticket_id = body.get("ticket_id")
        ext_type = body.get("type") or ""

        if not event_id or not isinstance(event_id, str):
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                error="missing or non-string `event_id`",
            )
        if ticket_id is not None and not isinstance(ticket_id, str):
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                error="`ticket_id` must be a string when present",
            )

        message_type = _ZENDESK_TYPE_MAP.get(
            ext_type, BoundaryMessageType.UNKNOWN
        )
        if message_type is BoundaryMessageType.UNKNOWN:
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.UNSUPPORTED_TYPE,
                external_message_id=event_id,
                external_conversation_id=ticket_id,
                message_type=message_type,
                error=f"unsupported zendesk type: {ext_type!r}",
            )

        emitted_at = _parse_timestamp(body.get("created_at"))
        canonical: dict[str, Any] = {
            "ticket_id": ticket_id,
            "type": ext_type,
            "subject": body.get("subject"),
            "status": body.get("status"),
            "priority": body.get("priority"),
            "requester_id": body.get("requester_id"),
            "assignee_id": body.get("assignee_id"),
            "comment": body.get("comment"),
            "tags": body.get("tags"),
        }
        return BoundaryNormalizationResult(
            status=BoundaryNormalizationStatus.OK,
            message_type=message_type,
            external_message_id=event_id,
            external_conversation_id=ticket_id,
            external_emitted_at=emitted_at,
            canonical_payload=canonical,
            metadata={
                "raw_type": ext_type,
                "source_subdomain": source.source_id,
            },
        )


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


__all__ = ["ZendeskWebhookAdapter"]
