"""AWS SES v2 sender boundary."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.policy import SMTP
from typing import Any, Protocol, cast
from urllib.parse import urlparse

from app.core.config import get_settings
from app.core.http import create_isolated_http_client
from app.core.ssrf import (
    PinnedIPAsyncHTTPTransport,
    ValidatedPublicHTTPSURL,
    validate_public_https_url,
)

_MAX_ERROR_BODY_CHARS = 2048


class SesSSRFValidator(Protocol):
    def __call__(
        self,
        url: str,
        *,
        allowed_hosts: Iterable[str] = (),
    ) -> ValidatedPublicHTTPSURL: ...
_SERVICE = "ses"
_ALGORITHM = "AWS4-HMAC-SHA256"
_DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class SesEmailSendRequest:
    region: str
    access_key_id: str
    secret_access_key: str
    from_email_address: str
    recipient_email_address: str
    subject: str
    body_text: str
    session_token: str | None = None
    endpoint_url: str | None = None
    configuration_set_name: str | None = None
    in_reply_to_message_id: str | None = None
    references_header: str | None = None
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class SesEmailSendResponse:
    provider_message_id: str
    status_code: int


class SesHTTPResponseProtocol(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...

    def json(self) -> Any: ...


class SesHTTPClientProtocol(Protocol):
    async def post(
        self,
        url: str,
        *,
        content: bytes,
        headers: Mapping[str, str],
        timeout: float,
    ) -> SesHTTPResponseProtocol: ...


class SesV2SendError(RuntimeError):
    """Raised when SES refuses or cannot complete a send."""

    def __init__(self, *, status_code: int, response_body: str) -> None:
        super().__init__(f"ses v2 send returned {status_code}")
        self.status_code = status_code
        self.response_body = response_body[:_MAX_ERROR_BODY_CHARS]


class SesV2EmailSender:
    """Serialize and POST an already-authorized SES email reply.

    ``endpoint_url`` is tenant-configurable and the request is SigV4-signed
    with AWS credentials, so the destination is SSRF-validated (HTTPS, public
    address only), host-allowlisted to the regional AWS SES host
    ``email.<region>.amazonaws.com`` (plus operator-approved extras), and
    pinned to its resolved IP before connecting; redirects are never followed
    (S-06 extension). An injected ``client`` is a test seam — the SSRF gate
    still runs via ``ssrf_validator``.
    """

    def __init__(
        self,
        *,
        client: SesHTTPClientProtocol | None = None,
        additional_allowed_hosts: tuple[str, ...] | None = None,
        ssrf_validator: SesSSRFValidator | None = None,
    ) -> None:
        self._client = client
        self._additional_allowed_hosts = additional_allowed_hosts
        self._ssrf_validator = ssrf_validator or validate_public_https_url

    def _resolved_allowed_hosts(self, *, region: str) -> tuple[str, ...]:
        extra = (
            self._additional_allowed_hosts
            if self._additional_allowed_hosts is not None
            else get_settings().ses_additional_allowed_hosts
        )
        return (f"email.{region}.amazonaws.com", *extra)

    async def send_email(
        self,
        request: SesEmailSendRequest,
    ) -> SesEmailSendResponse:
        payload = _send_email_payload(request)
        body = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        endpoint = _endpoint_url(
            region=request.region,
            endpoint_url=request.endpoint_url,
        )
        send_url = endpoint + "/v2/email/outbound-emails"
        validated = await asyncio.to_thread(
            self._ssrf_validator,
            send_url,
            allowed_hosts=self._resolved_allowed_hosts(region=request.region),
        )
        headers = _sigv4_headers(
            request=request,
            endpoint=endpoint,
            payload=body,
        )
        if self._client is not None:
            response = await self._client.post(
                validated.url,
                content=body,
                headers=headers,
                timeout=request.timeout_seconds,
            )
        else:
            transport = PinnedIPAsyncHTTPTransport(pinned_ip=validated.pinned_ip)
            async with create_isolated_http_client(
                transport=transport,
                timeout_seconds=request.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    validated.url,
                    content=body,
                    headers=headers,
                    timeout=request.timeout_seconds,
                    follow_redirects=False,
                )
        if not 200 <= response.status_code < 300:
            raise SesV2SendError(
                status_code=response.status_code,
                response_body=response.text,
            )
        return SesEmailSendResponse(
            provider_message_id=_provider_message_id(response.json()),
            status_code=response.status_code,
        )


def _send_email_payload(request: SesEmailSendRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "FromEmailAddress": request.from_email_address,
        "Destination": {
            "ToAddresses": [request.recipient_email_address],
        },
        "Content": {
            "Raw": {
                "Data": base64.b64encode(_raw_mime(request)).decode("ascii"),
            },
        },
    }
    if request.configuration_set_name:
        payload["ConfigurationSetName"] = request.configuration_set_name
    return payload


def _raw_mime(request: SesEmailSendRequest) -> bytes:
    message = EmailMessage(policy=SMTP)
    message["From"] = request.from_email_address
    message["To"] = request.recipient_email_address
    message["Subject"] = request.subject
    if request.in_reply_to_message_id:
        message["In-Reply-To"] = request.in_reply_to_message_id
    if request.references_header:
        message["References"] = request.references_header
    elif request.in_reply_to_message_id:
        message["References"] = request.in_reply_to_message_id
    message.set_content(request.body_text)
    return message.as_bytes(policy=SMTP)


def _endpoint_url(*, region: str, endpoint_url: str | None) -> str:
    if endpoint_url is not None and endpoint_url.strip():
        parsed = urlparse(endpoint_url.strip())
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("ses endpoint_url must be an https URL")
        return endpoint_url.rstrip("/")
    return f"https://email.{region}.amazonaws.com"


def _sigv4_headers(
    *,
    request: SesEmailSendRequest,
    endpoint: str,
    payload: bytes,
) -> dict[str, str]:
    parsed = urlparse(endpoint)
    host = parsed.netloc
    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(payload).hexdigest()
    headers = {
        "content-type": "application/json",
        "host": host,
        "x-amz-date": amz_date,
    }
    if request.session_token:
        headers["x-amz-security-token"] = request.session_token
    canonical_headers = "".join(
        f"{name}:{headers[name]}\n" for name in sorted(headers)
    )
    signed_headers = ";".join(sorted(headers))
    canonical_request = "\n".join(
        (
            "POST",
            "/v2/email/outbound-emails",
            "",
            canonical_headers,
            signed_headers,
            payload_hash,
        )
    )
    credential_scope = f"{date_stamp}/{request.region}/{_SERVICE}/aws4_request"
    string_to_sign = "\n".join(
        (
            _ALGORITHM,
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        )
    )
    signing_key = _signature_key(
        secret_key=request.secret_access_key,
        date_stamp=date_stamp,
        region=request.region,
    )
    signature = hmac.new(
        signing_key,
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    headers["authorization"] = (
        f"{_ALGORITHM} Credential={request.access_key_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return headers


def _signature_key(*, secret_key: str, date_stamp: str, region: str) -> bytes:
    key_date = _hmac(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    key_region = _hmac(key_date, region)
    key_service = _hmac(key_region, _SERVICE)
    return _hmac(key_service, "aws4_request")


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _provider_message_id(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        raise SesV2SendError(status_code=502, response_body="malformed_json")
    typed = cast(Mapping[str, Any], payload)
    message_id = typed.get("MessageId")
    if not isinstance(message_id, str) or not message_id.strip():
        raise SesV2SendError(
            status_code=502,
            response_body="missing_provider_message_id",
        )
    return message_id.strip()


__all__ = [
    "SesEmailSendRequest",
    "SesEmailSendResponse",
    "SesHTTPClientProtocol",
    "SesV2EmailSender",
    "SesV2SendError",
]
