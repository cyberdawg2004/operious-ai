"""Phase 2.5-F webhook router layering smoke."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.v1.routers.ingress import create_channel_webhook_ingress
from app.services.ticket_ingress_service import (
    TicketIngressRejected,
    TicketIngressServiceResult,
    WebhookDuplicateDeliveryResult,
)


class _StubWebhookService:
    def __init__(
        self,
        *,
        reject: bool = False,
        duplicate: bool = False,
    ) -> None:
        self.reject = reject
        self.duplicate = duplicate
        self.calls: list[dict[str, object]] = []

    async def process_channel_webhook(self, **kwargs: object):
        self.calls.append(kwargs)
        if self.reject:
            raise TicketIngressRejected(
                code="channel_webhook_verification_failed",
                reason="bad signature",
                status_code=401,
            )
        if self.duplicate:
            return WebhookDuplicateDeliveryResult()
        return TicketIngressServiceResult(
            ingress_id="ingress-1",
            canonical_envelope_id="event-1",
        )


class _FakeRequest:
    def __init__(
        self,
        *,
        body: bytes,
        headers: dict[str, str],
    ) -> None:
        self.headers = headers
        self._body = body

    async def body(self) -> bytes:
        return self._body


@pytest.mark.asyncio
async def test_channel_webhook_router_hands_off_to_service() -> None:
    service = _StubWebhookService()

    response = await create_channel_webhook_ingress(
        channel_type="email",
        request=_FakeRequest(
            body=b'{"message_id":"email-1","to":"support@example.com"}',
            headers={"content-type": "application/json"},
        ),  # type: ignore[arg-type]
        expected_tenant_id="tenant-alpha",
        service=service,  # type: ignore[arg-type]
    )

    assert response.ingress_id == "ingress-1"
    assert response.canonical_envelope_id == "event-1"
    assert response.status == "received"
    assert service.calls[0]["channel_type"] == "email"
    assert service.calls[0]["tenant_hint"] == "tenant-alpha"
    assert service.calls[0]["content_type"] == "application/json"


@pytest.mark.asyncio
async def test_channel_webhook_router_maps_rejection_to_401() -> None:
    service = _StubWebhookService(reject=True)

    with pytest.raises(HTTPException) as exc_info:
        await create_channel_webhook_ingress(
            channel_type="email",
            request=_FakeRequest(
                body=b'{"message_id":"email-1","to":"support@example.com"}',
                headers={"content-type": "application/json"},
            ),  # type: ignore[arg-type]
            expected_tenant_id=None,
            service=service,  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == {
        "code": "channel_webhook_verification_failed",
        "reason": "bad signature",
    }


@pytest.mark.asyncio
async def test_channel_webhook_router_returns_duplicate_delivery_ack() -> None:
    service = _StubWebhookService(duplicate=True)

    response = await create_channel_webhook_ingress(
        channel_type="email",
        request=_FakeRequest(
            body=b'{"message_id":"email-1","to":"support@example.com"}',
            headers={"content-type": "application/json"},
        ),  # type: ignore[arg-type]
        expected_tenant_id=None,
        service=service,  # type: ignore[arg-type]
    )

    assert response.status == "duplicate_delivery_acknowledged"
