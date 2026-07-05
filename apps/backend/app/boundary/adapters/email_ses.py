"""AWS SES inbound email boundary adapter.

This module is deliberately boundary-only: SNS verification, MIME parsing, and
canonical email normalization happen here; tenant lookup and governance remain
outside this package.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any, Protocol, cast
from urllib.parse import urlparse

import boto3
from botocore.config import Config as BotoConfig
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.boundary.adapters.base import BaseIngressAdapter
from app.core.config import Settings
from app.boundary.adapters.channel_webhooks import (
    canonical_channel_payload_keys,
    normalize_routing_address,
)
from app.boundary.enums import (
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundarySourceType,
)
from app.boundary.models.normalization import BoundaryNormalizationResult
from app.boundary.models.payload import IngressPayload
from app.boundary.models.source import BoundarySource
from app.core.http import get_shared_http_client

_MAX_ERROR_BODY_CHARS = 2048
_SUPPORTED_SNS_TYPES = frozenset({"Notification", "SubscriptionConfirmation"})
_SNS_CONFIRMATION_TYPES = frozenset({"SubscriptionConfirmation"})


class SnsVerificationError(RuntimeError):
    """SNS envelope verification failed."""


class SnsConfirmationError(RuntimeError):
    """SNS subscription confirmation failed."""


class SesEmailMimeError(RuntimeError):
    """SES notification could not be converted into a MIME email."""


class SnsCertificateFetcher(Protocol):
    async def fetch_certificate_pem(self, url: str) -> bytes: ...


class SnsSubscriptionConfirmer(Protocol):
    async def confirm_subscription(self, subscribe_url: str) -> None: ...


class SesRawEmailFetcher(Protocol):
    async def fetch_raw_email(
        self,
        *,
        bucket_name: str,
        object_key: str,
        tenant_id: str,
    ) -> bytes: ...


class S3SesRawEmailFetcher:
    """Fetch SES-routed raw email bytes from the bucket/key SES designates.

    SES routes emails over its inline-SNS size limit to S3 instead of
    embedding MIME in the notification; ``_s3_location()`` extracts which
    bucket+key holds it. This is the first concrete implementation of
    ``SesRawEmailFetcher`` — previously these emails (and any attachments
    inside them) never reached MIME parsing at all (PR-B1a's gap).

    boto3 is synchronous; ``fetch_raw_email`` wraps the blocking call with
    ``asyncio.to_thread`` so it composes with the rest of this module's
    async ingestion path without blocking the event loop.
    """

    __slots__ = ("_client",)

    def __init__(
        self,
        *,
        region: str,
        access_key_id: str,
        secret_access_key: str,
    ) -> None:
        self._client: Any = cast("Any", boto3).client(
            "s3",
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=BotoConfig(retries={"max_attempts": 3, "mode": "standard"}),
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "S3SesRawEmailFetcher":
        return cls(
            region=settings.LIVE_SES_REGION,
            access_key_id=settings.LIVE_SES_ACCESS_KEY_ID,
            secret_access_key=settings.LIVE_SES_SECRET_ACCESS_KEY,
        )

    async def fetch_raw_email(
        self,
        *,
        bucket_name: str,
        object_key: str,
        tenant_id: str,
    ) -> bytes:
        del tenant_id  # bucket+key are already fully qualified by SES
        return await asyncio.to_thread(self._get_object, bucket_name, object_key)

    def _get_object(self, bucket_name: str, object_key: str) -> bytes:
        response: dict[str, Any] = cast("dict[str, Any]", self._client.get_object(Bucket=bucket_name, Key=object_key))
        return cast("bytes", response["Body"].read())


@dataclass(frozen=True, slots=True)
class SnsVerifiedMessage:
    message_type: str
    message_id: str
    topic_arn: str
    timestamp: datetime
    message: str
    subscribe_url: str | None = None


class HttpSnsCertificateFetcher:
    """Fetch SNS signing certificates from validated AWS-owned URLs."""

    async def fetch_certificate_pem(self, url: str) -> bytes:
        validate_aws_sns_url(url, require_pem=True)
        response = await get_shared_http_client().get(url, timeout=5.0)
        if response.status_code != 200:
            raise SnsVerificationError(
                f"sns certificate fetch returned {response.status_code}"
            )
        return bytes(response.content)


class HttpSnsSubscriptionConfirmer:
    """Confirm an already-verified SNS subscription confirmation."""

    async def confirm_subscription(self, subscribe_url: str) -> None:
        validate_aws_sns_url(subscribe_url, require_pem=False)
        response = await get_shared_http_client().get(subscribe_url, timeout=5.0)
        if not 200 <= response.status_code < 300:
            body = response.text[:_MAX_ERROR_BODY_CHARS]
            raise SnsConfirmationError(
                f"sns subscription confirmation returned {response.status_code}: {body}"
            )


class SnsMessageVerifier:
    """Verify AWS SNS JSON envelopes using the documented canonical string."""

    def __init__(
        self,
        *,
        certificate_fetcher: SnsCertificateFetcher | None = None,
    ) -> None:
        self._certificate_fetcher = certificate_fetcher or HttpSnsCertificateFetcher()

    async def verify(
        self,
        *,
        payload: Mapping[str, Any],
        expected_topic_arn: str,
    ) -> SnsVerifiedMessage:
        message_type = _required_sns_text(payload, "Type")
        if message_type not in _SUPPORTED_SNS_TYPES:
            raise SnsVerificationError("unsupported sns message type")
        topic_arn = _required_sns_text(payload, "TopicArn")
        if topic_arn != expected_topic_arn:
            raise SnsVerificationError("sns topic arn mismatch")
        signing_cert_url = _required_sns_text(payload, "SigningCertURL")
        validate_aws_sns_url(signing_cert_url, require_pem=True)
        signature = _decode_signature(_required_sns_text(payload, "Signature"))
        signature_version = _required_sns_text(payload, "SignatureVersion")
        digest = _signature_digest(signature_version)
        canonical = _canonical_sns_string(payload, message_type=message_type)
        certificate_pem = await self._certificate_fetcher.fetch_certificate_pem(
            signing_cert_url
        )
        certificate = x509.load_pem_x509_certificate(certificate_pem)
        public_key = certificate.public_key()
        if not isinstance(public_key, rsa.RSAPublicKey):
            raise SnsVerificationError("sns certificate public key is not RSA")
        try:
            public_key.verify(
                signature,
                canonical.encode("utf-8"),
                padding.PKCS1v15(),
                digest,
            )
        except InvalidSignature as exc:
            raise SnsVerificationError("sns signature verification failed") from exc
        return SnsVerifiedMessage(
            message_type=message_type,
            message_id=_required_sns_text(payload, "MessageId"),
            topic_arn=topic_arn,
            timestamp=_parse_required_timestamp(
                _required_sns_text(payload, "Timestamp")
            ),
            message=_required_sns_text(payload, "Message"),
            subscribe_url=(
                _required_sns_text(payload, "SubscribeURL")
                if message_type in _SNS_CONFIRMATION_TYPES
                else None
            ),
        )


class SesEmailWebhookAdapter(BaseIngressAdapter):
    """Normalize a verified SES/SNS MIME email into the shared channel envelope."""

    DEFAULT_NAME = "tenant_ses_email_webhook_adapter"

    def __init__(
        self,
        *,
        routing_address: str,
        name: str | None = None,
    ) -> None:
        super().__init__(
            name=name or self.DEFAULT_NAME,
            source_type=BoundarySourceType.EMAIL,
        )
        self._routing_address = normalize_routing_address("email", routing_address)

    def normalize(
        self,
        *,
        source: BoundarySource,
        payload: IngressPayload,
    ) -> BoundaryNormalizationResult:
        body_object = payload.body
        if not isinstance(body_object, Mapping):
            return _malformed_result("SES email payload must be a mapping")
        body = cast(Mapping[str, Any], body_object)
        if body.get("signature_verified") is not True:
            return _unauthenticated_result("SES SNS signature was not verified")
        try:
            to_address = normalize_routing_address(
                "email",
                _required_body_text(body, "to"),
            )
            message_id = _required_body_text(body, "message_id")
        except ValueError as exc:
            return _malformed_result(str(exc))
        if not _email_route_matches(to_address, self._routing_address):
            return _malformed_result("email routing address mismatch")
        conversation_id = _first_text(body.get("conversation_id"), message_id)
        canonical = {
            key: body.get(key)
            for key in canonical_channel_payload_keys()
        }
        canonical["channel"] = "email"
        canonical["message_id"] = message_id
        canonical["conversation_id"] = conversation_id
        canonical["to"] = to_address
        canonical["attachments"] = list(_attachments(body))
        return BoundaryNormalizationResult(
            status=BoundaryNormalizationStatus.OK,
            message_type=BoundaryMessageType.MESSAGE_RECEIVED,
            external_message_id=message_id,
            external_conversation_id=conversation_id,
            external_emitted_at=_parse_timestamp(body.get("emitted_at")),
            canonical_payload=canonical,
            metadata={
                "signature_verified": True,
                "routing_address": to_address,
                "source_id": source.source_id,
            },
        )


def _email_route_matches(to_address: str, routing_address: str) -> bool:
    if to_address == routing_address:
        return True
    domain = routing_address.removeprefix("@")
    return "@" not in routing_address and to_address.endswith(f"@{domain}")


async def ses_sns_message_to_email_payload(
    *,
    sns_message: str,
    tenant_id: str,
    raw_email_fetcher: SesRawEmailFetcher | None = None,
) -> dict[str, Any]:
    """Parse an SES SNS message into the adapter's verified email payload."""

    notification = _decode_ses_notification(sns_message)
    raw_email = _raw_mime_from_notification(notification)
    if raw_email is None:
        s3_location = _s3_location(notification)
        if s3_location is None or raw_email_fetcher is None:
            raise SesEmailMimeError("SES notification does not include raw MIME")
        raw_email = await raw_email_fetcher.fetch_raw_email(
            bucket_name=s3_location[0],
            object_key=s3_location[1],
            tenant_id=tenant_id,
        )
    payload = parse_email_mime(raw_email)
    emitted_at = _first_text(
        _nested_text(notification, "mail", "timestamp"),
        payload.get("emitted_at"),
    )
    payload["emitted_at"] = emitted_at
    payload["source_event_type"] = _first_text(
        notification.get("notificationType"),
        notification.get("eventType"),
        payload.get("source_event_type"),
        "ses.received",
    )
    payload["signature_verified"] = True
    return payload


def parse_email_mime(raw_email: bytes) -> dict[str, Any]:
    """Parse RFC 5322 MIME into the shared canonical email envelope fields."""

    message = BytesParser(policy=policy.default).parsebytes(raw_email)
    message_id = _decoded_header_value(message, "Message-ID")
    from_header = _decoded_header_value(message, "From")
    from_address = _first_address(from_header)
    from_display_name = _first_display_name(from_header)
    to_address = _first_address(_decoded_header_value(message, "To"))
    subject = _decoded_header_value(message, "Subject")
    in_reply_to = _decoded_header_value(message, "In-Reply-To")
    references = _decoded_header_value(message, "References")
    text, attachments = _text_and_attachments(message)
    if message_id is None:
        raise SesEmailMimeError("email MIME Message-ID header is required")
    if to_address is None:
        raise SesEmailMimeError("email MIME To header is required")
    return {
        "channel": "email",
        "message_id": message_id,
        "conversation_id": _conversation_id(
            message_id=message_id,
            in_reply_to=in_reply_to,
            references=references,
        ),
        "from": from_address,
        "from_display_name": from_display_name,
        "to": to_address,
        "subject": subject,
        "text": text,
        "attachments": attachments,
        "source_event_type": "ses.received",
        "emitted_at": _decoded_header_value(message, "Date"),
    }


def extract_ses_routing_address_from_sns_message(sns_message: str) -> str:
    notification = _decode_ses_notification(sns_message)
    destination = _nested(notification, "mail", "destination")
    value = _first_sequence_text(destination)
    if value is None:
        value = _first_sequence_text(_nested(notification, "mail", "commonHeaders", "to"))
    if value is None:
        raw_email = _raw_mime_from_notification(notification)
        if raw_email is not None:
            parsed = BytesParser(policy=policy.default).parsebytes(raw_email)
            value = _decoded_header_value(parsed, "To")
    if value is None:
        raise SesEmailMimeError("SES notification routing address missing")
    address = _first_address(value)
    return normalize_routing_address("email", address or value)


def validate_aws_sns_url(url: str, *, require_pem: bool) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise SnsVerificationError("sns url must use https")
    if parsed.username or parsed.password or parsed.port is not None:
        raise SnsVerificationError("sns url must not include credentials or port")
    host = (parsed.hostname or "").lower()
    if not _is_aws_sns_host(host):
        raise SnsVerificationError("sns url host is not AWS-owned")
    if require_pem and not parsed.path.endswith(".pem"):
        raise SnsVerificationError("sns signing certificate url must end with .pem")


def _is_aws_sns_host(host: str) -> bool:
    return (
        host == "sns.amazonaws.com"
        or (host.startswith("sns.") and host.endswith(".amazonaws.com"))
    )


def _canonical_sns_string(
    payload: Mapping[str, Any],
    *,
    message_type: str,
) -> str:
    if message_type == "Notification":
        fields = ["Message", "MessageId"]
        if _optional_sns_text(payload, "Subject") is not None:
            fields.append("Subject")
        fields.extend(["Timestamp", "TopicArn", "Type"])
    else:
        fields = [
            "Message",
            "MessageId",
            "SubscribeURL",
            "Timestamp",
            "Token",
            "TopicArn",
            "Type",
        ]
    lines: list[str] = []
    for field in fields:
        lines.append(field)
        lines.append(_required_sns_text(payload, field))
    return "\n".join(lines) + "\n"


def _decode_signature(value: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise SnsVerificationError("sns signature is not valid base64") from exc


def _signature_digest(version: str) -> hashes.HashAlgorithm:
    if version == "1":
        return hashes.SHA1()
    if version == "2":
        return hashes.SHA256()
    raise SnsVerificationError("unsupported sns signature version")


def _decode_ses_notification(sns_message: str) -> Mapping[str, Any]:
    text = sns_message.strip()
    if not text:
        raise SesEmailMimeError("SES SNS message is empty")
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return {"content": sns_message}
    if not isinstance(decoded, Mapping):
        raise SesEmailMimeError("SES SNS message must decode to an object")
    return cast(Mapping[str, Any], decoded)


def _raw_mime_from_notification(notification: Mapping[str, Any]) -> bytes | None:
    for key in ("content", "raw_email", "rawEmail", "rawMessage"):
        value = notification.get(key)
        if isinstance(value, str) and value.strip():
            return value.encode("utf-8")
    encoded = _first_text(
        notification.get("contentBase64"),
        notification.get("rawEmailBase64"),
    )
    if encoded is None:
        return None
    try:
        return base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise SesEmailMimeError("SES raw MIME base64 is invalid") from exc


def _s3_location(notification: Mapping[str, Any]) -> tuple[str, str] | None:
    action = _mapping_or_none(_nested(notification, "receipt", "action"))
    candidates: list[Mapping[str, Any]] = []
    if action is not None:
        candidates.append(action)
    actions = _nested(notification, "receipt", "actions")
    if isinstance(actions, Sequence) and not isinstance(actions, str | bytes):
        action_items = cast(Sequence[Any], actions)
        candidates.extend(
            cast(Mapping[str, Any], item)
            for item in action_items
            if isinstance(item, Mapping)
        )
    for candidate in candidates:
        bucket = _first_text(candidate.get("bucketName"), candidate.get("bucket"))
        key = _first_text(candidate.get("objectKey"), candidate.get("key"))
        if bucket is not None and key is not None:
            return bucket, key
    return None


def _text_and_attachments(message: Message) -> tuple[str | None, list[dict[str, Any]]]:
    text_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[dict[str, Any]] = []
    parts = list(message.walk()) if message.is_multipart() else [message]
    for part in parts:
        if part.is_multipart():
            continue
        content_type = part.get_content_type()
        disposition = part.get_content_disposition()
        filename = part.get_filename()
        if disposition == "attachment" or filename:
            attachments.append(_attachment_summary(part))
            continue
        content = _part_text(part)
        if content is None:
            continue
        if content_type == "text/plain":
            text_parts.append(content)
        elif content_type == "text/html":
            html_parts.append(_strip_html(content))
    text = "\n\n".join(t.strip() for t in text_parts if t.strip())
    if not text:
        text = "\n\n".join(t.strip() for t in html_parts if t.strip())
    return (text or None), attachments


_ATTACHMENT_RAW_BYTES_KEY = "_raw_bytes"
"""Internal-only key carrying the decoded attachment binary.

This module is deliberately boundary-only (MIME parsing, no tenant
lookup, no storage) — see the module docstring. The binary rides along
in the parsed attachment dict so a tenant-aware caller (once tenant_id is
resolved) can persist it via AttachmentStorageService, but it MUST be
popped via ``pop_attachment_raw_bytes`` before the attachment dict is
placed anywhere that gets JSON-serialized (e.g. a canonical payload
persisted as JSONB) — raw bytes are not JSON-serializable and were never
meant to reach that path.
"""


def _attachment_summary(part: Message) -> dict[str, Any]:
    payload = part.get_payload(decode=True)
    size = len(payload) if payload is not None else 0
    filename = part.get_filename()
    if filename is not None:
        filename = _decode_header_text(filename)
    return {
        "filename": filename,
        "content_type": part.get_content_type(),
        "content_id": _decoded_header_value(part, "Content-ID"),
        "disposition": part.get_content_disposition(),
        "size_bytes": size,
        _ATTACHMENT_RAW_BYTES_KEY: payload if isinstance(payload, bytes) else None,
    }


def pop_attachment_raw_bytes(attachment: dict[str, Any]) -> bytes | None:
    """Extract and remove the decoded binary from a parsed attachment dict.

    Callers that persist attachments (see
    ``app.attachments.storage_service.AttachmentStorageService``) MUST call
    this for every attachment before the attachment dict is placed into any
    payload that gets JSON-serialized — the key is always stripped here,
    regardless of whether a binary was present.
    """
    value = attachment.pop(_ATTACHMENT_RAW_BYTES_KEY, None)
    return value if isinstance(value, bytes) else None


def _part_text(part: Message) -> str | None:
    if isinstance(part, EmailMessage):
        try:
            content = part.get_content()
        except (LookupError, UnicodeDecodeError):
            content = None
        if isinstance(content, str):
            return content
    payload = part.get_payload(decode=True)
    if not isinstance(payload, bytes):
        return None
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value)


def _conversation_id(
    *,
    message_id: str,
    in_reply_to: str | None,
    references: str | None,
) -> str:
    if in_reply_to:
        return in_reply_to
    if references:
        parts = references.split()
        if parts:
            return parts[-1]
    return message_id


def _required_sns_text(payload: Mapping[str, Any], key: str) -> str:
    value = _optional_sns_text(payload, key)
    if value is None:
        raise SnsVerificationError(f"sns field {key} is required")
    return value


def _optional_sns_text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _required_body_text(payload: Mapping[str, Any], key: str) -> str:
    value = _first_text(payload.get(key))
    if value is None:
        raise ValueError(f"{key} is required")
    return value


def _parse_required_timestamp(value: str) -> datetime:
    parsed = _parse_timestamp(value)
    if parsed is None:
        raise SnsVerificationError("sns timestamp is invalid")
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            pass
        try:
            return parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    return None


def _decoded_header_value(message: Message, name: str) -> str | None:
    value = message.get(name)
    if value is None:
        return None
    return _decode_header_text(str(value))


def _decode_header_text(value: str) -> str:
    return str(make_header(decode_header(value))).strip()


def _first_address(value: str | None) -> str | None:
    if value is None:
        return None
    addresses = getaddresses([value])
    for _, address in addresses:
        if address:
            return address
    return value.strip() or None


def _first_display_name(value: str | None) -> str | None:
    if value is None:
        return None
    addresses = getaddresses([value])
    for name, _ in addresses:
        cleaned = name.strip()
        if cleaned:
            return cleaned
    return None


def _nested(value: Mapping[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = cast(Mapping[str, Any], current).get(key)
    return current


def _nested_text(value: Mapping[str, Any], *keys: str) -> str | None:
    return _first_text(_nested(value, *keys))


def _mapping_or_none(value: Any) -> Mapping[str, Any] | None:
    return cast(Mapping[str, Any], value) if isinstance(value, Mapping) else None


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_sequence_text(value: Any) -> str | None:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        values = cast(Sequence[Any], value)
        for item in values:
            text = _first_text(item)
            if text is not None:
                return text
        return None
    return _first_text(value)


def _attachments(body: Mapping[str, Any]) -> tuple[object, ...]:
    """Return attachment metadata with the internal raw-bytes key stripped.

    Defensive: the production path (TicketIngressService) already pops
    ``_raw_bytes`` via ``pop_attachment_raw_bytes`` before this normalize()
    ever runs, but this guarantees the canonical payload — which gets
    JSON-serialized into ``boundary_ingress.canonical_payload`` — can never
    carry a raw ``bytes`` value even if some other caller skips that step.
    """
    value = body.get("attachments")
    if not isinstance(value, list):
        return ()
    cleaned: list[object] = []
    for item in cast(list[object], value):
        if isinstance(item, dict) and _ATTACHMENT_RAW_BYTES_KEY in item:
            item = {
                key: val
                for key, val in cast(dict[str, Any], item).items()
                if key != _ATTACHMENT_RAW_BYTES_KEY
            }
        cleaned.append(cast("object", item))
    return tuple(cleaned)


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


__all__ = [
    "HttpSnsCertificateFetcher",
    "HttpSnsSubscriptionConfirmer",
    "S3SesRawEmailFetcher",
    "SesEmailMimeError",
    "SesEmailWebhookAdapter",
    "SesRawEmailFetcher",
    "SnsCertificateFetcher",
    "SnsConfirmationError",
    "SnsMessageVerifier",
    "SnsSubscriptionConfirmer",
    "SnsVerificationError",
    "SnsVerifiedMessage",
    "extract_ses_routing_address_from_sns_message",
    "parse_email_mime",
    "pop_attachment_raw_bytes",
    "ses_sns_message_to_email_payload",
    "validate_aws_sns_url",
]
