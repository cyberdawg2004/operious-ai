"""`TwilioVoiceAdapter` — reference normalisation example.

Handles a minimal subset of Twilio's voice-status webhook shape:

```
{
  "CallSid": "CA...",
  "AccountSid": "AC...",
  "From": "+...",
  "To": "+...",
  "CallStatus": "ringing|in-progress|completed|busy|failed|no-answer|canceled",
  "Direction": "inbound|outbound-...",
  "Timestamp": "..."  (RFC2822 or ISO8601)
}
```

Stream-frame webhooks (`MediaFormat`, `Track`, `Sequence`) are
classified as `STREAM_FRAME` with `external_message_id` set to
``CallSid:Sequence`` so each frame has a unique replay key.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
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


_CALL_STATUS_MAP: dict[str, BoundaryMessageType] = {
    "ringing": BoundaryMessageType.STATUS_UPDATE,
    "queued": BoundaryMessageType.STATUS_UPDATE,
    "in-progress": BoundaryMessageType.STATUS_UPDATE,
    "completed": BoundaryMessageType.STATUS_UPDATE,
    "busy": BoundaryMessageType.STATUS_UPDATE,
    "failed": BoundaryMessageType.STATUS_UPDATE,
    "no-answer": BoundaryMessageType.STATUS_UPDATE,
    "canceled": BoundaryMessageType.STATUS_UPDATE,
}


class TwilioVoiceAdapter(BaseIngressAdapter):
    """Reference Twilio voice-webhook adapter."""

    DEFAULT_NAME = "twilio_voice_adapter"

    def __init__(self, *, name: str | None = None) -> None:
        super().__init__(
            name=name or self.DEFAULT_NAME,
            source_type=BoundarySourceType.TWILIO_VOICE,
        )

    def normalize(
        self,
        *,
        source: BoundarySource,
        payload: IngressPayload,
    ) -> BoundaryNormalizationResult:
        raw_body = payload.body
        if not isinstance(raw_body, Mapping):
            raise BoundaryNormalizationError(
                "Twilio payload must be a mapping (form fields)"
            )
        body = cast(Mapping[str, Any], raw_body)

        call_sid: Any = body.get("CallSid")
        if not isinstance(call_sid, str) or not call_sid:
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                error="missing or non-string `CallSid`",
            )

        # Stream-frame variant.
        sequence: Any = body.get("Sequence") or body.get("MediaSeq")
        track: Any = body.get("Track")
        if track is not None or sequence is not None:
            seq_str = (
                str(sequence) if sequence is not None else "0"
            )
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.OK,
                message_type=BoundaryMessageType.STREAM_FRAME,
                external_message_id=f"{call_sid}:{seq_str}",
                external_conversation_id=call_sid,
                external_emitted_at=_parse_timestamp(
                    body.get("Timestamp")
                ),
                canonical_payload={
                    "track": track,
                    "sequence": seq_str,
                    "media_format": body.get("MediaFormat"),
                },
                metadata={
                    "account_sid": body.get("AccountSid"),
                },
            )

        # Status-event variant.
        status_value: Any = body.get("CallStatus")
        message_type = _CALL_STATUS_MAP.get(
            status_value or "",
            BoundaryMessageType.UNKNOWN,
        )
        if message_type is BoundaryMessageType.UNKNOWN:
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.UNSUPPORTED_TYPE,
                external_message_id=call_sid,
                external_conversation_id=call_sid,
                error=(
                    f"unsupported twilio CallStatus: "
                    f"{status_value!r}"
                ),
            )

        canonical: dict[str, Any] = {
            "from": body.get("From"),
            "to": body.get("To"),
            "call_status": status_value,
            "direction": body.get("Direction"),
            "duration_sec": body.get("CallDuration"),
        }
        return BoundaryNormalizationResult(
            status=BoundaryNormalizationStatus.OK,
            message_type=message_type,
            external_message_id=call_sid,
            external_conversation_id=call_sid,
            external_emitted_at=_parse_timestamp(
                body.get("Timestamp")
            ),
            canonical_payload=canonical,
            metadata={
                "account_sid": body.get("AccountSid"),
            },
        )


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except ValueError:
            pass
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        # `email.utils.parsedate_to_datetime` returns `datetime` per
        # the typeshed; the runtime branch for a `None` return path
        # was retired with Python 3.10+. Trust the type contract.
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


__all__ = ["TwilioVoiceAdapter"]
