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

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, cast

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
        raw_body = payload.body
        body = _mapping_or_none(raw_body)
        if body is None:
            raise BoundaryNormalizationError(
                "WhatsApp payload must be a mapping"
            )

        entries_value = body.get("entry")
        entries = (
            cast(list[object], entries_value)
            if isinstance(entries_value, list)
            else []
        )
        if not entries:
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                error="missing or empty `entry` array",
            )
        first_entry = _mapping_or_none(entries[0])
        if first_entry is None:
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                error="`entry[0]` must be a mapping",
            )
        changes_value = first_entry.get("changes")
        changes = (
            cast(list[object], changes_value)
            if isinstance(changes_value, list)
            else []
        )
        if not changes:
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                error="missing or empty `changes` array",
            )
        first_change = _mapping_or_none(changes[0])
        if first_change is None:
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                error="`changes[0]` must be a mapping",
            )
        value = _mapping_or_none(first_change.get("value"))
        if value is None:
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                error="`changes[0].value` must be a mapping",
            )

        messages_value = value.get("messages")
        messages = (
            cast(list[object], messages_value)
            if isinstance(messages_value, list)
            else []
        )
        statuses_value = value.get("statuses")
        statuses = (
            cast(list[object], statuses_value)
            if isinstance(statuses_value, list)
            else []
        )

        if messages:
            return self._normalize_message(
                source=source,
                value=value,
                messages=messages,
            )
        if statuses:
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
        messages: list[object],
    ) -> BoundaryNormalizationResult:
        first = _mapping_or_none(messages[0])
        if first is None:
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                error="`messages[0]` must be a mapping",
            )
        ext_message_id: Any = first.get("id")
        wa_from: Any = first.get("from")
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

        timestamp_raw: Any = first.get("timestamp")
        emitted_at = _parse_timestamp(timestamp_raw)
        msg_type: Any = first.get("type") or "text"
        text_body: Any = None
        text_value = _mapping_or_none(first.get("text"))
        if text_value is not None:
            text_body = text_value.get("body")
        metadata = _mapping_or_none(value.get("metadata"))

        canonical: dict[str, Any] = {
            "from": wa_from,
            "type": msg_type,
            "text": text_body,
            "phone_number_id": (
                metadata.get("phone_number_id")
                if metadata is not None
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
        statuses: list[object],
    ) -> BoundaryNormalizationResult:
        first = _mapping_or_none(statuses[0])
        if first is None:
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                error="`statuses[0]` must be a mapping",
            )
        ext_message_id: Any = first.get("id")
        recipient: Any = first.get("recipient_id")
        status_value: Any = first.get("status")
        if not isinstance(ext_message_id, str) or not ext_message_id:
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                error="missing or non-string status `id`",
            )

        emitted_at = _parse_timestamp(first.get("timestamp"))
        metadata = _mapping_or_none(value.get("metadata"))
        canonical: dict[str, Any] = {
            "status": status_value,
            "recipient_id": recipient,
            "phone_number_id": (
                metadata.get("phone_number_id")
                if metadata is not None
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


def _mapping_or_none(value: object) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return cast(Mapping[str, Any], value)
    return None


__all__ = ["WhatsAppWebhookAdapter"]
