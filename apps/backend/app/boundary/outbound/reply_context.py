"""Derive the customer-facing reply target from the original inbound
dispatch envelope.

Single source of truth for "who do we actually reply to, and what's the
subject/threading" -- the real customer's address from the inbound
message itself (e.g. the email's ``From`` header), never the SES/
provider envelope address. Used by both the build-time auto-send path
(``resolution_runtime`` via ``agent_tasks``) and the case-approval-driven
delivery path (``case_approval_service``), so the two paths can never
derive a different answer for the same dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class OutboundReplyContext:
    source_channel: str | None = None
    recipient: str | None = None
    recipient_display_name: str | None = None
    source: str | None = None
    subject: str | None = None
    thread_context: str | None = None
    in_reply_to_message_id: str | None = None
    references_header: str | None = None
    phone_number_id: str | None = None


def extract_outbound_reply_context(
    payload: Mapping[str, Any],
) -> OutboundReplyContext:
    channel = normalised_reply_channel(
        payload_text(payload, "channel") or payload_text(payload, "channel_type")
    )
    if channel not in {"email", "whatsapp"}:
        return OutboundReplyContext()
    message_id = payload_text(payload, "message_id")
    conversation_id = payload_text(payload, "conversation_id")
    thread_context = conversation_id or message_id
    phone_number_id = payload_text(payload, "phone_number_id")
    source = payload_text(payload, "to")
    if channel == "whatsapp" and source is None:
        source = phone_number_id
    return OutboundReplyContext(
        source_channel=channel,
        recipient=payload_text(payload, "from"),
        recipient_display_name=(
            payload_text(payload, "from_display_name")
            if channel == "email"
            else None
        ),
        source=source,
        subject=(
            reply_subject(payload_text(payload, "subject"))
            if channel == "email"
            else None
        ),
        thread_context=thread_context,
        in_reply_to_message_id=message_id if channel == "email" else None,
        references_header=(
            email_references_header(
                conversation_id=conversation_id,
                message_id=message_id,
            )
            if channel == "email"
            else None
        ),
        phone_number_id=phone_number_id,
    )


def outbound_reply_context_from_dispatch_body(
    body: Mapping[str, Any],
) -> OutboundReplyContext:
    """Mirrors the dispatch-content extraction's canonical_payload-first
    fallback: prefer ``body["canonical_payload"]`` when present, else the
    raw dispatch body itself."""
    canonical_payload = body.get("canonical_payload")
    if isinstance(canonical_payload, Mapping):
        return extract_outbound_reply_context(canonical_payload)
    return extract_outbound_reply_context(body)


def reply_subject(subject: str | None) -> str:
    if subject is None:
        return "Re: Support request"
    if subject.lower().startswith("re:"):
        return subject
    return f"Re: {subject}"


def email_references_header(
    *,
    conversation_id: str | None,
    message_id: str | None,
) -> str | None:
    references = tuple(
        value
        for value in (conversation_id, message_id)
        if value is not None and value.strip()
    )
    if not references:
        return None
    return " ".join(dict.fromkeys(references))


def normalised_reply_channel(value: str | None) -> str | None:
    if value is None:
        return None
    channel = value.strip().lower()
    if channel in {"email", "whatsapp"}:
        return channel
    return None


def payload_text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


__all__ = [
    "OutboundReplyContext",
    "extract_outbound_reply_context",
    "outbound_reply_context_from_dispatch_body",
    "reply_subject",
    "email_references_header",
    "normalised_reply_channel",
    "payload_text",
]
