"""SSRF/egress hardening for customer-facing channel senders (S-06 ext).

WhatsApp ``graph_api_base_url`` and SES ``endpoint_url`` are tenant-
configurable and the sends carry provider credentials, so every destination
must be SSRF-validated, host-allowlisted, and pinned. These tests prove the
gate runs BEFORE any send and rejects off-allowlist destinations. Allowlist
rejection happens before DNS resolution, so these are hermetic.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pytest

from app.boundary.outbound.email_ses import SesEmailSendRequest, SesV2EmailSender
from app.boundary.outbound.whatsapp import (
    WhatsAppGraphSender,
    WhatsAppTextMessageRequest,
)
from app.core.ssrf import SSRFValidationError, ValidatedPublicHTTPSURL


class _FakeResponse:
    def __init__(self, *, status_code: int, payload: Mapping[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = "ok"

    def json(self) -> Any:
        return self._payload


class _CapturingClient:
    def __init__(self, *, payload: Mapping[str, Any]) -> None:
        self.url: str | None = None
        self._payload = payload

    async def post(self, url: str, **_: Any) -> _FakeResponse:
        self.url = url
        return _FakeResponse(status_code=200, payload=self._payload)


def _stub_validator(pinned_ip: str = "203.0.113.10"):
    def _validate(
        url: str,
        *,
        allowed_hosts: Iterable[str] = (),
    ) -> ValidatedPublicHTTPSURL:
        del allowed_hosts
        return ValidatedPublicHTTPSURL(
            url=url,
            hostname="provider.example",
            port=443,
            pinned_ip=pinned_ip,
        )

    return _validate


def _whatsapp_request(base_url: str) -> WhatsAppTextMessageRequest:
    return WhatsAppTextMessageRequest(
        graph_api_base_url=base_url,
        graph_api_version="v19.0",
        phone_number_id="1234567890",
        access_token="secret-token",
        recipient_phone_number="15551234567",
        body="Hello",
    )


def _ses_request(endpoint_url: str | None) -> SesEmailSendRequest:
    return SesEmailSendRequest(
        region="us-east-1",
        access_key_id="AKIA_TEST",
        secret_access_key="secret",
        from_email_address="support@tenant.example",
        recipient_email_address="customer@example.com",
        subject="Re: your ticket",
        body_text="Thanks for reaching out.",
        endpoint_url=endpoint_url,
    )


@pytest.mark.asyncio
async def test_whatsapp_rejects_off_allowlist_base_url() -> None:
    sender = WhatsAppGraphSender()  # real validator, default allowlist
    with pytest.raises(SSRFValidationError):
        await sender.send_text_message(
            _whatsapp_request("https://internal.metadata.local")
        )


@pytest.mark.asyncio
async def test_whatsapp_rejects_non_https_base_url() -> None:
    sender = WhatsAppGraphSender()
    with pytest.raises(SSRFValidationError):
        await sender.send_text_message(
            _whatsapp_request("http://graph.facebook.com")
        )


@pytest.mark.asyncio
async def test_whatsapp_posts_to_validated_url_when_allowed() -> None:
    client = _CapturingClient(payload={"messages": [{"id": "wamid.TEST"}]})
    sender = WhatsAppGraphSender(
        client=client,
        ssrf_validator=_stub_validator(),
    )
    result = await sender.send_text_message(
        _whatsapp_request("https://graph.facebook.com")
    )
    assert result.provider_message_id == "wamid.TEST"
    assert client.url == (
        "https://graph.facebook.com/v19.0/1234567890/messages"
    )


@pytest.mark.asyncio
async def test_ses_rejects_off_allowlist_endpoint_override() -> None:
    sender = SesV2EmailSender()  # real validator; only regional AWS host allowed
    with pytest.raises(SSRFValidationError):
        await sender.send_email(_ses_request("https://internal.metadata.local"))


@pytest.mark.asyncio
async def test_ses_rejects_non_https_endpoint_override() -> None:
    sender = SesV2EmailSender()
    with pytest.raises(ValueError):
        # _endpoint_url rejects non-https before SSRF; still fail-closed.
        await sender.send_email(_ses_request("http://email.us-east-1.amazonaws.com"))


@pytest.mark.asyncio
async def test_ses_posts_to_validated_regional_url_when_allowed() -> None:
    client = _CapturingClient(payload={"MessageId": "ses-test-id"})
    sender = SesV2EmailSender(
        client=client,
        ssrf_validator=_stub_validator(),
    )
    result = await sender.send_email(_ses_request(None))
    assert result.provider_message_id == "ses-test-id"
    assert client.url == (
        "https://email.us-east-1.amazonaws.com/v2/email/outbound-emails"
    )
