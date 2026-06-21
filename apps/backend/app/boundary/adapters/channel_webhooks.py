"""Tenant-owned channel webhook adapters.

These adapters verify tenant-scoped webhook signatures and translate
channel-specific webhook payloads into one shared ticket-message
canonical payload. They are edge translators only: no governance,
session, execution, or coordination imports belong here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any, cast

from app.boundary.adapters.base import BaseIngressAdapter
from app.boundary.enums import (
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundarySourceType,
)
from app.boundary.exceptions import BoundaryNormalizationError
from app.boundary.models.normalization import BoundaryNormalizationResult
from app.boundary.models.payload import IngressPayload
from app.boundary.models.source import BoundarySource
from app.core.config import get_settings
from app.core.twilio_signature import (
    TWILIO_CANONICAL_URL_HEADER,
    TWILIO_SIGNATURE_HEADER,
    verify_twilio_signature,
)
from app.core.webhook_url import (
    CanonicalWebhookUrlError,
    derive_canonical_webhook_url,
)


@dataclass(frozen=True, slots=True)
class ChannelWebhookSecurityContext:
    """Timestamp + nonce extracted from a signed channel webhook."""

    timestamp: datetime
    nonce: str


_CANONICAL_CHANNEL_PAYLOAD_KEYS = frozenset(
    {
        "channel",
        "message_id",
        "conversation_id",
        "from",
        "to",
        "subject",
        "text",
        "attachments",
        "source_event_type",
        "source_language",
    }
)


class EmailWebhookAdapter(BaseIngressAdapter):
    """Email webhook adapter for SES SNS or SMTP-to-HTTP relay payloads."""

    DEFAULT_NAME = "tenant_email_webhook_adapter"

    def __init__(
        self,
        *,
        webhook_secret: str,
        routing_address: str,
        name: str | None = None,
    ) -> None:
        super().__init__(
            name=name or self.DEFAULT_NAME,
            source_type=BoundarySourceType.EMAIL,
        )
        self._webhook_secret = _require_secret(webhook_secret)
        self._routing_address = normalize_routing_address(
            "email", routing_address
        )

    def normalize(
        self,
        *,
        source: BoundarySource,
        payload: IngressPayload,
    ) -> BoundaryNormalizationResult:
        body = _mapping_body(payload, "Email payload must be a mapping")
        if not _verify_sha256_signature(
            secret=self._webhook_secret,
            payload=payload,
            header_names=(
                "x-operious-signature",
                "x-email-signature",
                "x-amz-sns-message-signature",
            ),
        ):
            return _unauthenticated_result("email signature verification failed")

        to_address = normalize_routing_address(
            "email", extract_email_routing_address(body, payload.headers)
        )
        if to_address != self._routing_address:
            return _malformed_result("email routing address mismatch")

        message_id = _first_text(
            body.get("message_id"),
            body.get("messageId"),
            body.get("id"),
            _nested(body, "mail", "messageId"),
        )
        if message_id is None:
            return _malformed_result("missing email message id")

        common_headers = _mapping_or_empty(_nested(body, "mail", "commonHeaders"))
        from_address = _first_text(
            body.get("from"),
            _first_sequence_text(common_headers.get("from")),
            _header(payload.headers, "from"),
        )
        subject = _first_text(
            body.get("subject"),
            common_headers.get("subject"),
        )
        text = _first_text(
            body.get("text"),
            body.get("body"),
            body.get("content"),
            body.get("message"),
            _nested(body, "receipt", "action", "objectKey"),
        )
        conversation_id = _first_text(
            body.get("thread_id"),
            body.get("in_reply_to"),
            body.get("conversation_id"),
            message_id,
        )
        return _ok_result(
            channel="email",
            message_id=message_id,
            conversation_id=conversation_id,
            from_address=from_address,
            to_address=to_address,
            subject=subject,
            text=text,
            attachments=_attachments(body),
            source_event_type=_first_text(body.get("event_type"), body.get("type")),
            emitted_at=_parse_timestamp(
                _first_text(body.get("timestamp"), _nested(body, "mail", "timestamp"))
            ),
            metadata={
                "signature_verified": True,
                "routing_address": to_address,
                "source_id": source.source_id,
            },
        )


class TenantWhatsAppWebhookAdapter(BaseIngressAdapter):
    """WhatsApp adapter supporting Meta and Twilio-style webhooks."""

    DEFAULT_NAME = "tenant_whatsapp_webhook_adapter"

    def __init__(
        self,
        *,
        webhook_secret: str,
        routing_address: str,
        name: str | None = None,
    ) -> None:
        super().__init__(
            name=name or self.DEFAULT_NAME,
            source_type=BoundarySourceType.WHATSAPP,
        )
        self._webhook_secret = _require_secret(webhook_secret)
        self._routing_address = normalize_routing_address(
            "whatsapp", routing_address
        )

    def normalize(
        self,
        *,
        source: BoundarySource,
        payload: IngressPayload,
    ) -> BoundaryNormalizationResult:
        body = _mapping_body(payload, "WhatsApp payload must be a mapping")
        if not (
            _verify_sha256_signature(
                secret=self._webhook_secret,
                payload=payload,
                header_names=("x-hub-signature-256", "x-operious-signature"),
            )
            or _verify_twilio_signature(
                secret=self._webhook_secret,
                payload=payload,
            )
        ):
            return _unauthenticated_result(
                "whatsapp signature verification failed"
            )

        if _is_twilio_whatsapp(body):
            return self._normalize_twilio(
                source=source,
                payload=payload,
                body=body,
            )
        return self._normalize_meta(source=source, payload=payload, body=body)

    def _normalize_meta(
        self,
        *,
        source: BoundarySource,
        payload: IngressPayload,
        body: Mapping[str, Any],
    ) -> BoundaryNormalizationResult:
        value = _first_whatsapp_value(body)
        if value is None:
            return _malformed_result("missing whatsapp value")
        metadata = _mapping_or_empty(value.get("metadata"))
        route = normalize_routing_address(
            "whatsapp",
            _first_text(
                metadata.get("phone_number_id"),
                metadata.get("display_phone_number"),
                extract_whatsapp_routing_address(body, payload.headers),
            ),
        )
        if route != self._routing_address:
            return _malformed_result("whatsapp routing address mismatch")
        messages_value = value.get("messages")
        messages = (
            cast(list[object], messages_value)
            if isinstance(messages_value, list)
            else []
        )
        if not messages:
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.UNSUPPORTED_TYPE,
                error="whatsapp webhook contains no messages",
            )
        first = _mapping_or_none(messages[0])
        if first is None:
            return _malformed_result("whatsapp message must be a mapping")
        message_id = _first_text(first.get("id"))
        sender = _first_text(first.get("from"))
        if message_id is None:
            return _malformed_result("missing whatsapp message id")
        text = None
        text_value = _mapping_or_none(first.get("text"))
        if text_value is not None:
            text = _first_text(text_value.get("body"))
        return _ok_result(
            channel="whatsapp",
            message_id=message_id,
            conversation_id=_first_text(sender, message_id),
            from_address=sender,
            to_address=route,
            subject=None,
            text=text,
            attachments=_meta_media_placeholders(first),
            source_event_type=_first_text(first.get("type"), "message"),
            emitted_at=_parse_timestamp(first.get("timestamp")),
            metadata={
                "signature_verified": True,
                "routing_address": route,
                "source_id": source.source_id,
            },
        )

    def _normalize_twilio(
        self,
        *,
        source: BoundarySource,
        payload: IngressPayload,
        body: Mapping[str, Any],
    ) -> BoundaryNormalizationResult:
        route = normalize_routing_address(
            "whatsapp", extract_whatsapp_routing_address(body, payload.headers)
        )
        if route != self._routing_address:
            return _malformed_result("whatsapp routing address mismatch")
        message_id = _first_text(
            body.get("MessageSid"),
            body.get("SmsMessageSid"),
            body.get("SmsSid"),
        )
        if message_id is None:
            return _malformed_result("missing twilio whatsapp message id")
        sender = normalize_routing_address("whatsapp", _first_text(body.get("From")))
        return _ok_result(
            channel="whatsapp",
            message_id=message_id,
            conversation_id=_first_text(body.get("WaId"), sender, message_id),
            from_address=sender,
            to_address=route,
            subject=None,
            text=_first_text(body.get("Body")),
            attachments=(),
            source_event_type="message",
            emitted_at=_parse_timestamp(body.get("Timestamp")),
            metadata={
                "signature_verified": True,
                "routing_address": route,
                "source_id": source.source_id,
            },
        )


class ShulexWebhookAdapter(BaseIngressAdapter):
    """Shulex event-webhook adapter."""

    DEFAULT_NAME = "tenant_shulex_webhook_adapter"

    def __init__(
        self,
        *,
        webhook_secret: str,
        routing_address: str,
        name: str | None = None,
    ) -> None:
        super().__init__(
            name=name or self.DEFAULT_NAME,
            source_type=BoundarySourceType.SHULEX,
        )
        self._webhook_secret = _require_secret(webhook_secret)
        self._routing_address = normalize_routing_address(
            "shulex", routing_address
        )

    def normalize(
        self,
        *,
        source: BoundarySource,
        payload: IngressPayload,
    ) -> BoundaryNormalizationResult:
        body = _mapping_body(payload, "Shulex payload must be a mapping")
        if not _verify_sha256_signature(
            secret=self._webhook_secret,
            payload=payload,
            header_names=("x-shulex-signature", "x-operious-signature"),
        ):
            return _unauthenticated_result("shulex signature verification failed")
        route = normalize_routing_address(
            "shulex", extract_shulex_routing_address(body, payload.headers)
        )
        if route != self._routing_address:
            return _malformed_result("shulex routing address mismatch")
        message_id = _first_text(
            body.get("event_id"),
            body.get("message_id"),
            body.get("id"),
        )
        if message_id is None:
            return _malformed_result("missing shulex event id")
        return _ok_result(
            channel="shulex",
            message_id=message_id,
            conversation_id=_first_text(
                body.get("conversation_id"),
                body.get("ticket_id"),
                body.get("order_id"),
                message_id,
            ),
            from_address=_first_text(
                body.get("customer_id"),
                body.get("from"),
                _nested(body, "customer", "id"),
            ),
            to_address=route,
            subject=_first_text(body.get("subject"), body.get("title")),
            text=_first_text(body.get("text"), body.get("message"), body.get("content")),
            attachments=_attachments(body),
            source_event_type=_first_text(body.get("event_type"), body.get("type")),
            emitted_at=_parse_timestamp(
                _first_text(body.get("created_at"), body.get("timestamp"))
            ),
            metadata={
                "signature_verified": True,
                "routing_address": route,
                "source_id": source.source_id,
            },
        )


class LarkWebhookAdapter(BaseIngressAdapter):
    """Lark event-callback adapter."""

    DEFAULT_NAME = "tenant_lark_webhook_adapter"

    def __init__(
        self,
        *,
        webhook_secret: str,
        routing_address: str,
        name: str | None = None,
    ) -> None:
        super().__init__(
            name=name or self.DEFAULT_NAME,
            source_type=BoundarySourceType.LARK,
        )
        self._webhook_secret = _require_secret(webhook_secret)
        self._routing_address = normalize_routing_address(
            "lark", routing_address
        )

    def normalize(
        self,
        *,
        source: BoundarySource,
        payload: IngressPayload,
    ) -> BoundaryNormalizationResult:
        body = _mapping_body(payload, "Lark payload must be a mapping")
        if not _verify_lark_signature(
            secret=self._webhook_secret,
            payload=payload,
        ):
            return _unauthenticated_result("lark signature verification failed")
        route = normalize_routing_address(
            "lark", extract_lark_routing_address(body, payload.headers)
        )
        if route != self._routing_address:
            return _malformed_result("lark routing address mismatch")
        event = _mapping_or_empty(body.get("event"))
        header = _mapping_or_empty(body.get("header"))
        message = _mapping_or_empty(event.get("message"))
        message_id = _first_text(
            header.get("event_id"),
            message.get("message_id"),
            body.get("event_id"),
        )
        if message_id is None:
            return _malformed_result("missing lark event id")
        return _ok_result(
            channel="lark",
            message_id=message_id,
            conversation_id=_first_text(
                message.get("chat_id"),
                message.get("open_chat_id"),
                event.get("chat_id"),
                message_id,
            ),
            from_address=_first_text(
                _nested(event, "sender", "sender_id", "open_id"),
                _nested(event, "sender", "sender_id", "user_id"),
            ),
            to_address=route,
            subject=_first_text(body.get("subject")),
            text=_lark_text(message.get("content")),
            attachments=(),
            source_event_type=_first_text(header.get("event_type"), body.get("type")),
            emitted_at=_parse_timestamp(header.get("create_time")),
            metadata={
                "signature_verified": True,
                "routing_address": route,
                "source_id": source.source_id,
            },
        )


def extract_routing_address(
    *,
    channel_type: str,
    body: Any,
    headers: Mapping[str, str],
) -> str:
    if not isinstance(body, Mapping):
        raise ValueError("channel webhook body must be a mapping")
    typed_body = cast(Mapping[str, Any], body)
    channel = channel_type.strip().lower()
    if channel == "email":
        return normalize_routing_address(
            channel, extract_email_routing_address(typed_body, headers)
        )
    if channel == "whatsapp":
        return normalize_routing_address(
            channel, extract_whatsapp_routing_address(typed_body, headers)
        )
    if channel == "shulex":
        return normalize_routing_address(
            channel, extract_shulex_routing_address(typed_body, headers)
        )
    if channel == "lark":
        return normalize_routing_address(
            channel, extract_lark_routing_address(typed_body, headers)
        )
    raise ValueError(f"unsupported channel type: {channel_type!r}")


def extract_webhook_security_context(
    *,
    channel_type: str,
    body: Any,
    headers: Mapping[str, str],
) -> ChannelWebhookSecurityContext:
    if not isinstance(body, Mapping):
        raise ValueError("channel webhook body must be a mapping")
    typed_body = cast(Mapping[str, Any], body)
    channel = channel_type.strip().lower()
    if channel == "email":
        timestamp_value = _first_text(
            _header(headers, "x-operious-webhook-timestamp"),
            _header(headers, "x-email-timestamp"),
            _header(headers, "x-amz-sns-message-timestamp"),
            typed_body.get("timestamp"),
            _nested(typed_body, "mail", "timestamp"),
        )
        nonce = _first_text(
            _header(headers, "x-operious-webhook-nonce"),
            _header(headers, "x-email-nonce"),
            typed_body.get("nonce"),
            typed_body.get("message_id"),
            typed_body.get("messageId"),
            typed_body.get("id"),
            _nested(typed_body, "mail", "messageId"),
        )
    elif channel == "whatsapp":
        value = _first_whatsapp_value(typed_body)
        messages = value.get("messages") if value is not None else None
        first: Mapping[str, Any] = {}
        if (
            isinstance(messages, list)
            and messages
            and isinstance(messages[0], Mapping)
        ):
            first = cast(Mapping[str, Any], messages[0])
        timestamp_value = _first_text(
            _header(headers, "x-operious-webhook-timestamp"),
            _header(headers, "x-whatsapp-timestamp"),
            typed_body.get("Timestamp"),
            typed_body.get("timestamp"),
            first.get("timestamp"),
        )
        nonce = _first_text(
            _header(headers, "x-operious-webhook-nonce"),
            _header(headers, "x-whatsapp-nonce"),
            typed_body.get("nonce"),
            typed_body.get("MessageSid"),
            typed_body.get("SmsMessageSid"),
            typed_body.get("SmsSid"),
            first.get("id"),
        )
    elif channel == "shulex":
        timestamp_value = _first_text(
            _header(headers, "x-operious-webhook-timestamp"),
            _header(headers, "x-shulex-timestamp"),
            typed_body.get("created_at"),
            typed_body.get("timestamp"),
        )
        nonce = _first_text(
            _header(headers, "x-operious-webhook-nonce"),
            _header(headers, "x-shulex-nonce"),
            typed_body.get("nonce"),
            typed_body.get("event_id"),
            typed_body.get("message_id"),
            typed_body.get("id"),
        )
    elif channel == "lark":
        header = _mapping_or_empty(typed_body.get("header"))
        event = _mapping_or_empty(typed_body.get("event"))
        message = _mapping_or_empty(event.get("message"))
        timestamp_value = _first_text(
            _header(headers, "x-lark-request-timestamp"),
            _header(headers, "x-operious-webhook-timestamp"),
            header.get("create_time"),
            typed_body.get("timestamp"),
        )
        nonce = _first_text(
            _header(headers, "x-lark-request-nonce"),
            _header(headers, "x-operious-webhook-nonce"),
            typed_body.get("nonce"),
            header.get("event_id"),
            message.get("message_id"),
            typed_body.get("event_id"),
        )
    else:
        raise ValueError(f"unsupported channel type: {channel_type!r}")

    timestamp = _parse_timestamp(timestamp_value)
    if timestamp is None:
        raise ValueError("webhook timestamp missing or invalid")
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)
    if nonce is None:
        raise ValueError("webhook nonce missing")
    return ChannelWebhookSecurityContext(timestamp=timestamp, nonce=nonce)


def extract_email_routing_address(
    body: Mapping[str, Any],
    headers: Mapping[str, str],
) -> str:
    value = _first_text(
        body.get("routing_address"),
        body.get("to"),
        body.get("recipient"),
        _first_sequence_text(_nested(body, "mail", "destination")),
        _first_sequence_text(_nested(body, "mail", "commonHeaders", "to")),
        _header(headers, "x-original-to"),
        _header(headers, "to"),
    )
    if value is None:
        raise ValueError("email routing address missing")
    addresses = getaddresses([value])
    if addresses:
        parsed = addresses[0][1]
        if parsed:
            return parsed
    return value


def extract_whatsapp_routing_address(
    body: Mapping[str, Any],
    headers: Mapping[str, str],
) -> str:
    value = _first_whatsapp_value(body)
    metadata = _mapping_or_empty(
        value.get("metadata") if value is not None else None
    )
    route = _first_text(
        body.get("routing_address"),
        metadata.get("phone_number_id"),
        metadata.get("display_phone_number"),
        body.get("To"),
        _header(headers, "x-whatsapp-phone-number-id"),
    )
    if route is None:
        raise ValueError("whatsapp routing address missing")
    return route


def extract_shulex_routing_address(
    body: Mapping[str, Any],
    headers: Mapping[str, str],
) -> str:
    value = _first_text(
        body.get("routing_address"),
        body.get("shop_id"),
        body.get("store_id"),
        _nested(body, "shop", "id"),
        _nested(body, "store", "id"),
        _header(headers, "x-shulex-shop-id"),
    )
    if value is None:
        raise ValueError("shulex routing address missing")
    return value


def extract_lark_routing_address(
    body: Mapping[str, Any],
    headers: Mapping[str, str],
) -> str:
    header = _mapping_or_empty(body.get("header"))
    event = _mapping_or_empty(body.get("event"))
    message = _mapping_or_empty(event.get("message"))
    value = _first_text(
        body.get("routing_address"),
        header.get("app_id"),
        body.get("app_id"),
        message.get("chat_id"),
        _header(headers, "x-lark-app-id"),
    )
    if value is None:
        raise ValueError("lark routing address missing")
    return value


def normalize_routing_address(channel_type: str, value: str | None) -> str:
    if value is None:
        raise ValueError("routing address missing")
    text = value.strip()
    if not text:
        raise ValueError("routing address missing")
    channel = channel_type.strip().lower()
    if channel == "email":
        return text.lower()
    if channel == "whatsapp":
        return text.removeprefix("whatsapp:").strip()
    return text


def canonical_channel_payload_keys() -> frozenset[str]:
    return _CANONICAL_CHANNEL_PAYLOAD_KEYS


_META_MEDIA_TYPES = ("image", "document", "audio", "video", "sticker")


def _meta_media_placeholders(message: Mapping[str, Any]) -> tuple[object, ...]:
    """Pending-attachment placeholders for a Meta WhatsApp message.

    This adapter is a pure, synchronous translator with no DB session
    (see module docstring: "edge translators only") — it cannot fetch
    media bytes or write the durable whatsapp_media_fetch_records row
    itself. It only carries the media id/mime_type forward as a
    ``storage_status: "pending"`` placeholder; B1.5's background fetch
    task resolves it later (see app.services.ticket_ingress_service
    and app.boundary.whatsapp_media_fetch). ``storage_status`` is
    deliberately never "stored" here, so
    app.workers.agent_tasks._extract_attachment_ids correctly excludes
    an unresolved placeholder from attachment_ids.
    """
    placeholders: list[object] = []
    for media_type in _META_MEDIA_TYPES:
        media = _mapping_or_none(message.get(media_type))
        if media is None:
            continue
        media_id = _first_text(media.get("id"))
        if media_id is None:
            continue
        placeholders.append(
            {
                "storage_status": "pending",
                "channel": "whatsapp",
                "provider": "meta",
                "media_id": media_id,
                "content_type_declared": _first_text(media.get("mime_type")),
            }
        )
    return tuple(placeholders)


def _ok_result(
    *,
    channel: str,
    message_id: str,
    conversation_id: str | None,
    from_address: str | None,
    to_address: str,
    subject: str | None,
    text: str | None,
    attachments: tuple[object, ...],
    source_event_type: str | None,
    emitted_at: datetime | None,
    metadata: Mapping[str, Any],
) -> BoundaryNormalizationResult:
    canonical = {
        "channel": channel,
        "message_id": message_id,
        "conversation_id": conversation_id,
        "from": from_address,
        "to": to_address,
        "subject": subject,
        "text": text,
        "attachments": list(attachments),
        "source_event_type": source_event_type,
    }
    return BoundaryNormalizationResult(
        status=BoundaryNormalizationStatus.OK,
        message_type=BoundaryMessageType.MESSAGE_RECEIVED,
        external_message_id=message_id,
        external_conversation_id=conversation_id,
        external_emitted_at=emitted_at,
        canonical_payload=canonical,
        metadata=dict(metadata),
    )


def _unauthenticated_result(error: str) -> BoundaryNormalizationResult:
    return BoundaryNormalizationResult(
        status=BoundaryNormalizationStatus.UNAUTHENTICATED,
        error=error,
    )


def _malformed_result(error: str) -> BoundaryNormalizationResult:
    return BoundaryNormalizationResult(
        status=BoundaryNormalizationStatus.MALFORMED,
        error=error,
    )


def _mapping_body(payload: IngressPayload, error: str) -> Mapping[str, Any]:
    body_object: object = payload.body
    if not isinstance(body_object, Mapping):
        raise BoundaryNormalizationError(error)
    return cast(Mapping[str, Any], body_object)


def _verify_sha256_signature(
    *,
    secret: str,
    payload: IngressPayload,
    header_names: tuple[str, ...],
) -> bool:
    signature = payload.signature
    if signature is None:
        for name in header_names:
            signature = _header(payload.headers, name)
            if signature:
                break
    if not signature:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        _signature_bytes(payload),
        hashlib.sha256,
    ).hexdigest()
    supplied = signature.strip()
    if supplied.startswith("sha256="):
        supplied = supplied.removeprefix("sha256=")
    return hmac.compare_digest(supplied.lower(), expected.lower())


def _verify_twilio_signature(
    *,
    secret: str,
    payload: IngressPayload,
) -> bool:
    signature = _header(payload.headers, TWILIO_SIGNATURE_HEADER)
    body_object: object = payload.body
    if not signature or not isinstance(body_object, Mapping):
        return False
    body = cast(Mapping[str, Any], body_object)
    url = _twilio_canonical_url(payload)
    if url is None:
        return False
    return verify_twilio_signature(
        auth_token=secret,
        url=url,
        params=body,
        signature=signature,
    )


def _twilio_canonical_url(payload: IngressPayload) -> str | None:
    """The URL the Twilio signature is verified against.

    Derived server-side from ``PUBLIC_BASE_URL`` + the trusted request path
    (#23). The client-supplied ``x-operious-webhook-url`` header is honoured
    only when ``WEBHOOK_TRUST_URL_HEADER`` is explicitly enabled (non-prod).
    """
    settings = get_settings()
    if settings.WEBHOOK_TRUST_URL_HEADER:
        return _header(payload.headers, TWILIO_CANONICAL_URL_HEADER)
    if payload.request_path is None:
        return None
    try:
        return derive_canonical_webhook_url(
            public_base_url=settings.public_base_url_normalized,
            request_path=payload.request_path,
            query_string="",
        )
    except CanonicalWebhookUrlError:
        return None


def _verify_lark_signature(
    *,
    secret: str,
    payload: IngressPayload,
) -> bool:
    signature = _header(payload.headers, "x-lark-signature")
    timestamp = _header(payload.headers, "x-lark-request-timestamp")
    nonce = _header(payload.headers, "x-lark-request-nonce")
    if not signature or timestamp is None or nonce is None:
        return False
    signed = timestamp.encode("utf-8") + nonce.encode("utf-8")
    signed += _signature_bytes(payload)
    expected = hmac.new(
        secret.encode("utf-8"),
        signed,
        hashlib.sha256,
    ).hexdigest()
    supplied = signature.strip()
    if supplied.startswith("sha256="):
        supplied = supplied.removeprefix("sha256=")
    return hmac.compare_digest(supplied.lower(), expected.lower())


def _signature_bytes(payload: IngressPayload) -> bytes:
    if payload.raw_bytes is not None:
        return payload.raw_bytes
    return json.dumps(
        payload.body,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def _require_secret(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("webhook_secret must be non-empty")
    return text


def _mapping_or_empty(value: object) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], value) if isinstance(value, Mapping) else {}


def _mapping_or_none(value: object) -> Mapping[str, Any] | None:
    return cast(Mapping[str, Any], value) if isinstance(value, Mapping) else None


def _first_whatsapp_value(body: Mapping[str, Any]) -> Mapping[str, Any] | None:
    entries_value = body.get("entry")
    entries = (
        cast(list[object], entries_value)
        if isinstance(entries_value, list)
        else []
    )
    if not entries:
        return None
    first_entry = _mapping_or_none(entries[0])
    if first_entry is None:
        return None
    changes_value = first_entry.get("changes")
    changes = (
        cast(list[object], changes_value)
        if isinstance(changes_value, list)
        else []
    )
    if not changes:
        return None
    first_change = _mapping_or_none(changes[0])
    if first_change is None:
        return None
    return _mapping_or_none(first_change.get("value"))


def _is_twilio_whatsapp(body: Mapping[str, Any]) -> bool:
    return any(key in body for key in ("MessageSid", "SmsMessageSid", "SmsSid"))


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
        elif isinstance(value, (int, float)):
            return str(value)
    return None


def _first_sequence_text(value: Any) -> str | None:
    if isinstance(value, list | tuple):
        items = cast(Sequence[object], value)
        for item in items:
            text = _first_text(item)
            if text is not None:
                return text
    return _first_text(value)


def _nested(value: Mapping[str, Any], *keys: str) -> object | None:
    current: object = value
    for key in keys:
        current_mapping = _mapping_or_none(current)
        if current_mapping is None:
            return None
        current = current_mapping.get(key)
    return current


def _attachments(body: Mapping[str, Any]) -> tuple[object, ...]:
    value = body.get("attachments")
    if isinstance(value, list):
        return tuple(cast(list[object], value))
    return ()


def _lark_text(content: Any) -> str | None:
    if isinstance(content, str):
        text = content.strip()
        if not text:
            return None
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            return text
        decoded_mapping = _mapping_or_none(decoded)
        if decoded_mapping is not None:
            return _first_text(decoded_mapping.get("text"))
        return text
    content_mapping = _mapping_or_none(content)
    if content_mapping is not None:
        return _first_text(content_mapping.get("text"))
    return None


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number = number / 1000
        return datetime.fromtimestamp(number, tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():
            return _parse_timestamp(float(text))
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            pass
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


__all__ = [
    "ChannelWebhookSecurityContext",
    "EmailWebhookAdapter",
    "LarkWebhookAdapter",
    "ShulexWebhookAdapter",
    "TenantWhatsAppWebhookAdapter",
    "canonical_channel_payload_keys",
    "extract_email_routing_address",
    "extract_lark_routing_address",
    "extract_routing_address",
    "extract_shulex_routing_address",
    "extract_whatsapp_routing_address",
    "extract_webhook_security_context",
    "normalize_routing_address",
]
