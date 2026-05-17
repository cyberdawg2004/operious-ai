"""`WhatsAppWebhookAdapter` — reference normalisation example.

Handles a minimal subset of the WhatsApp Cloud API webhook shape:

```
{
  "entry": [{
    "changes": [{
      "value": {
        "metadata": {"phone_number_id": "..."},
        "messages": [{"id": "wamid....", "from": "...", "timestamp": "...", "type": "text", "text": {"body": "..."}}]
      }
    }]
  }]
}
```

Multi-message webhooks are NOT split — the adapter normalises only
the first message and surfaces the count in metadata. Splitting is
a caller-side concern OUTSIDE the substrate.
"""

from __future__ import annotations

from datetime import datetime, timezone
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


class WhatsAppWebhookAdapter(BaseIngressAdapter):
    """Reference WhatsApp Cloud API webhook adapter."""

    DEFAULT_NAME = "whatsapp_webhook_adapter"

    def __init__(self, *, name: str | None = None) -> None:
        super().__init__(
            name=name or self.DEFAULT_NAME,
            source_type=BoundarySourceType.WHATSAPP,
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
                "WhatsApp payload must be a mapping"
            )

        entries = body.get("entry") or []
        if not isinstance(entries, list) or not entries:
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                error="missing or empty `entry` array",
            )
        first_entry = entries[0]
        if not isinstance(first_entry, Mapping):
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                error="`entry[0]` must be a mapping",
            )
        changes = first_entry.get("changes") or []
        if not isinstance(changes, list) or not changes:
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                error="missing or empty `changes` array",
            )
        first_change = changes[0]
        if not isinstance(first_change, Mapping):
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                error="`changes[0]` must be a mapping",
            )
        value = first_change.get("value")
        if not isinstance(value, Mapping):
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                error="`changes[0].value` must be a mapping",
            )

        messages = value.get("messages") or []
        statuses = value.get("statuses") or []

        if isinstance(messages, list) and messages:
            return self._normalize_message(
                source=source,
                value=value,
                messages=messages,
            )
        if isinstance(statuses, list) and statuses:
            return self._normalize_status(
                source=source,
                value=value,
                statuses=statuses,
            )

        return BoundaryNormalizationResult(
            status=BoundaryNormalizationStatus.UNSUPPORTED_TYPE,
            error="payload contains neither messages nor statuses",
        )

    def _normalize_message(
        self,
        *,
        source: BoundarySource,
        value: Mapping[str, Any],
        messages: list[Any],
    ) -> BoundaryNormalizationResult:
        first = messages[0]
        if not isinstance(first, Mapping):
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                error="`messages[0]` must be a mapping",
            )
        ext_message_id = first.get("id")
        wa_from = first.get("from")
        if not isinstance(ext_message_id, str) or not ext_message_id:
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                error="missing or non-string message `id`",
            )
        if not isinstance(wa_from, str) or not wa_from:
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                error="missing or non-string message `from`",
            )

        timestamp_raw = first.get("timestamp")
        emitted_at = _parse_timestamp(timestamp_raw)
        msg_type = first.get("type") or "text"
        text_body = None
        if isinstance(first.get("text"), Mapping):
            text_body = first["text"].get("body")

        canonical: dict[str, Any] = {
            "from": wa_from,
            "type": msg_type,
            "text": text_body,
            "phone_number_id": (
                value.get("metadata", {}).get("phone_number_id")
                if isinstance(value.get("metadata"), Mapping)
                else None
            ),
        }
        return BoundaryNormalizationResult(
            status=BoundaryNormalizationStatus.OK,
            message_type=BoundaryMessageType.MESSAGE_RECEIVED,
            external_message_id=ext_message_id,
            external_conversation_id=wa_from,
            external_emitted_at=emitted_at,
            canonical_payload=canonical,
            metadata={
                "messages_count": len(messages),
                "source_phone_number_id": source.source_id,
            },
        )

    def _normalize_status(
        self,
        *,
        source: BoundarySource,
        value: Mapping[str, Any],
        statuses: list[Any],
    ) -> BoundaryNormalizationResult:
        first = statuses[0]
        if not isinstance(first, Mapping):
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                error="`statuses[0]` must be a mapping",
            )
        ext_message_id = first.get("id")
        recipient = first.get("recipient_id")
        status_value = first.get("status")
        if not isinstance(ext_message_id, str) or not ext_message_id:
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                error="missing or non-string status `id`",
            )

        emitted_at = _parse_timestamp(first.get("timestamp"))
        canonical: dict[str, Any] = {
            "status": status_value,
            "recipient_id": recipient,
            "phone_number_id": (
                value.get("metadata", {}).get("phone_number_id")
                if isinstance(value.get("metadata"), Mapping)
                else None
            ),
        }
        return BoundaryNormalizationResult(
            status=BoundaryNormalizationStatus.OK,
            message_type=BoundaryMessageType.STATUS_UPDATE,
            external_message_id=ext_message_id,
            external_conversation_id=(
                recipient if isinstance(recipient, str) else None
            ),
            external_emitted_at=emitted_at,
            canonical_payload=canonical,
            metadata={
                "statuses_count": len(statuses),
                "source_phone_number_id": source.source_id,
            },
        )


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        if value.isdigit():
            return datetime.fromtimestamp(
                int(value), tz=timezone.utc
            )
        try:
            return datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except ValueError:
            return None
    return None


__all__ = ["WhatsAppWebhookAdapter"]
