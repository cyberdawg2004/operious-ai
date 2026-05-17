"""Reference-adapter normalisation tests.

Covers:

* Zendesk webhook → canonical fields
* WhatsApp Cloud API webhook → canonical fields
* Twilio Voice webhook → canonical fields
* Malformed payloads return MALFORMED status (no exception raised
  — the substrate-level normaliser is responsible for catching;
  these tests target the adapters directly using the substrate
  contract, so we expect them to raise BoundaryNormalizationError
  for hard-shape violations).
"""

from __future__ import annotations

import pytest

from app.boundary.adapters.builtin.twilio_voice import (
    TwilioVoiceAdapter,
)
from app.boundary.adapters.builtin.whatsapp import (
    WhatsAppWebhookAdapter,
)
from app.boundary.adapters.builtin.zendesk import (
    ZendeskWebhookAdapter,
)
from app.boundary.enums import (
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundarySourceType,
)
from app.boundary.exceptions import BoundaryNormalizationError
from app.boundary.models.payload import IngressPayload
from app.boundary.models.source import BoundarySource


def _source(source_type: BoundarySourceType) -> BoundarySource:
    return BoundarySource(
        source_type=source_type,
        source_id="acct-1",
        tenant_id="tenant-1",
    )


# ─── ZendeskWebhookAdapter ──────────────────────────────────────────


def test_zendesk_normalises_ticket_comment() -> None:
    adapter = ZendeskWebhookAdapter()
    payload = IngressPayload(
        body={
            "event_id": "ze-evt-1",
            "ticket_id": "t-100",
            "type": "ticket.comment_created",
            "subject": "hello",
            "comment": {"body": "hi"},
            "created_at": "2026-01-01T00:00:00Z",
        }
    )
    result = adapter.normalize(
        source=_source(BoundarySourceType.ZENDESK),
        payload=payload,
    )
    assert result.is_ok
    assert (
        result.message_type is BoundaryMessageType.MESSAGE_RECEIVED
    )
    assert result.external_message_id == "ze-evt-1"
    assert result.external_conversation_id == "t-100"
    assert result.external_emitted_at is not None


def test_zendesk_unsupported_type_classified() -> None:
    adapter = ZendeskWebhookAdapter()
    payload = IngressPayload(
        body={
            "event_id": "ze-evt-2",
            "ticket_id": "t-100",
            "type": "ticket.merged",
        }
    )
    result = adapter.normalize(
        source=_source(BoundarySourceType.ZENDESK),
        payload=payload,
    )
    assert (
        result.status
        is BoundaryNormalizationStatus.UNSUPPORTED_TYPE
    )
    assert result.external_message_id == "ze-evt-2"


def test_zendesk_rejects_non_mapping() -> None:
    adapter = ZendeskWebhookAdapter()
    with pytest.raises(BoundaryNormalizationError):
        adapter.normalize(
            source=_source(BoundarySourceType.ZENDESK),
            payload=IngressPayload(body="not-a-mapping"),
        )


def test_zendesk_missing_event_id_yields_malformed() -> None:
    adapter = ZendeskWebhookAdapter()
    result = adapter.normalize(
        source=_source(BoundarySourceType.ZENDESK),
        payload=IngressPayload(
            body={"ticket_id": "t-1", "type": "ticket.created"}
        ),
    )
    assert result.status is BoundaryNormalizationStatus.MALFORMED


# ─── WhatsAppWebhookAdapter ─────────────────────────────────────────


def test_whatsapp_normalises_text_message() -> None:
    adapter = WhatsAppWebhookAdapter()
    payload = IngressPayload(
        body={
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {
                                    "phone_number_id": "pn-1"
                                },
                                "messages": [
                                    {
                                        "id": "wamid.AAA",
                                        "from": "447700900000",
                                        "timestamp": "1735689600",
                                        "type": "text",
                                        "text": {"body": "hi"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }
    )
    result = adapter.normalize(
        source=_source(BoundarySourceType.WHATSAPP),
        payload=payload,
    )
    assert result.is_ok
    assert result.external_message_id == "wamid.AAA"
    assert result.external_conversation_id == "447700900000"
    assert (
        result.message_type is BoundaryMessageType.MESSAGE_RECEIVED
    )


def test_whatsapp_normalises_status_event() -> None:
    adapter = WhatsAppWebhookAdapter()
    payload = IngressPayload(
        body={
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {
                                        "id": "wamid.BBB",
                                        "recipient_id": "447700900000",
                                        "status": "delivered",
                                        "timestamp": "1735689600",
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
    )
    result = adapter.normalize(
        source=_source(BoundarySourceType.WHATSAPP),
        payload=payload,
    )
    assert result.is_ok
    assert (
        result.message_type is BoundaryMessageType.STATUS_UPDATE
    )
    assert result.external_message_id == "wamid.BBB"


def test_whatsapp_empty_entries_malformed() -> None:
    adapter = WhatsAppWebhookAdapter()
    result = adapter.normalize(
        source=_source(BoundarySourceType.WHATSAPP),
        payload=IngressPayload(body={"entry": []}),
    )
    assert result.status is BoundaryNormalizationStatus.MALFORMED


# ─── TwilioVoiceAdapter ─────────────────────────────────────────────


def test_twilio_normalises_call_status() -> None:
    adapter = TwilioVoiceAdapter()
    payload = IngressPayload(
        body={
            "CallSid": "CA1",
            "AccountSid": "AC1",
            "From": "+1",
            "To": "+2",
            "CallStatus": "completed",
            "Direction": "inbound",
            "Timestamp": "2026-01-01T00:00:00Z",
        }
    )
    result = adapter.normalize(
        source=_source(BoundarySourceType.TWILIO_VOICE),
        payload=payload,
    )
    assert result.is_ok
    assert (
        result.message_type is BoundaryMessageType.STATUS_UPDATE
    )
    assert result.external_message_id == "CA1"
    assert result.external_conversation_id == "CA1"


def test_twilio_normalises_stream_frame() -> None:
    adapter = TwilioVoiceAdapter()
    payload = IngressPayload(
        body={
            "CallSid": "CA1",
            "Track": "inbound_track",
            "Sequence": 7,
            "MediaFormat": "audio/x-mulaw",
        }
    )
    result = adapter.normalize(
        source=_source(BoundarySourceType.TWILIO_VOICE),
        payload=payload,
    )
    assert result.is_ok
    assert (
        result.message_type is BoundaryMessageType.STREAM_FRAME
    )
    assert result.external_message_id == "CA1:7"


def test_twilio_unsupported_status_classified() -> None:
    adapter = TwilioVoiceAdapter()
    payload = IngressPayload(
        body={"CallSid": "CA1", "CallStatus": "weird-state"}
    )
    result = adapter.normalize(
        source=_source(BoundarySourceType.TWILIO_VOICE),
        payload=payload,
    )
    assert (
        result.status
        is BoundaryNormalizationStatus.UNSUPPORTED_TYPE
    )


def test_twilio_missing_call_sid_malformed() -> None:
    adapter = TwilioVoiceAdapter()
    result = adapter.normalize(
        source=_source(BoundarySourceType.TWILIO_VOICE),
        payload=IngressPayload(body={"CallStatus": "completed"}),
    )
    assert result.status is BoundaryNormalizationStatus.MALFORMED
