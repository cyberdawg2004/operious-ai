"""Wedge 1 webhook freshness, signature, and replay windows."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Mapping

import pytest

from app.boundary.persistence import (
    BoundaryIngressQuery,
    InMemoryBoundaryPersistence,
)
from app.services.ticket_ingress_service import (
    TicketIngressRejected,
    TicketIngressService,
)
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.enums import TenantChannelStatus, TenantChannelType
from app.tenant.persistence import InMemoryTenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime

MASTER_KEY = "wedge-1-webhook-master-key-32-bytes-min"
TENANT_ID = "tenant-wedge-1-webhook"

CHANNEL_CASES = (
    (TenantChannelType.EMAIL, "support@example.com"),
    (TenantChannelType.WHATSAPP, "phone-number-123"),
    (TenantChannelType.SHULEX, "shop-42"),
    (TenantChannelType.LARK, "cli_a1b2c3"),
)


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("channel_type", "routing_address"), CHANNEL_CASES)
async def test_channel_webhook_valid_signature_fresh_nonce_accepted(
    channel_type: TenantChannelType,
    routing_address: str,
) -> None:
    boundary_store = InMemoryBoundaryPersistence()
    service = await _service_with_channel(
        boundary_store=boundary_store,
        channel_type=channel_type,
        routing_address=routing_address,
    )
    timestamp = datetime.now(timezone.utc)
    body = _body(
        channel_type=channel_type,
        routing_address=routing_address,
        timestamp=timestamp,
        nonce=f"{channel_type.value}-fresh",
    )
    raw_body = _raw(body)

    result = await service.process_channel_webhook(
        channel_type=channel_type.value,
        body=body,
        headers=_signed_headers(
            channel_type=channel_type,
            secret=_secret(channel_type),
            raw_body=raw_body,
            timestamp=timestamp,
            nonce=f"{channel_type.value}-fresh",
        ),
        raw_body=raw_body,
        content_type="application/json",
    )

    assert result.ingress_id
    page = await boundary_store.list_ingress(
        BoundaryIngressQuery(),
        expected_tenant_id=TENANT_ID,
    )
    assert page.total == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("channel_type", "routing_address"), CHANNEL_CASES)
async def test_channel_webhook_duplicate_nonce_returns_ack_without_new_ingress(
    channel_type: TenantChannelType,
    routing_address: str,
) -> None:
    boundary_store = InMemoryBoundaryPersistence()
    service = await _service_with_channel(
        boundary_store=boundary_store,
        channel_type=channel_type,
        routing_address=routing_address,
    )
    timestamp = datetime.now(timezone.utc)
    nonce = f"{channel_type.value}-duplicate"
    body = _body(
        channel_type=channel_type,
        routing_address=routing_address,
        timestamp=timestamp,
        nonce=nonce,
    )
    raw_body = _raw(body)
    headers = _signed_headers(
        channel_type=channel_type,
        secret=_secret(channel_type),
        raw_body=raw_body,
        timestamp=timestamp,
        nonce=nonce,
    )

    first = await service.process_channel_webhook(
        channel_type=channel_type.value,
        body=body,
        headers=headers,
        raw_body=raw_body,
        content_type="application/json",
    )
    second = await service.process_channel_webhook(
        channel_type=channel_type.value,
        body=body,
        headers=headers,
        raw_body=raw_body,
        content_type="application/json",
    )

    assert first.ingress_id
    assert second.status == "duplicate_delivery_acknowledged"
    page = await boundary_store.list_ingress(
        BoundaryIngressQuery(),
        expected_tenant_id=TENANT_ID,
    )
    assert page.total == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("channel_type", "routing_address"), CHANNEL_CASES)
async def test_channel_webhook_invalid_signature_returns_401(
    channel_type: TenantChannelType,
    routing_address: str,
) -> None:
    boundary_store = InMemoryBoundaryPersistence()
    service = await _service_with_channel(
        boundary_store=boundary_store,
        channel_type=channel_type,
        routing_address=routing_address,
    )
    timestamp = datetime.now(timezone.utc)
    body = _body(
        channel_type=channel_type,
        routing_address=routing_address,
        timestamp=timestamp,
        nonce=f"{channel_type.value}-invalid",
    )

    with pytest.raises(TicketIngressRejected) as exc_info:
        await service.process_channel_webhook(
            channel_type=channel_type.value,
            body=body,
            headers=_invalid_signature_headers(
                channel_type=channel_type,
                timestamp=timestamp,
                nonce=f"{channel_type.value}-invalid",
            ),
            raw_body=_raw(body),
            content_type="application/json",
        )

    assert exc_info.value.code == "invalid_signature"
    assert exc_info.value.status_code == 401
    page = await boundary_store.list_ingress(BoundaryIngressQuery())
    assert page.total == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(("channel_type", "routing_address"), CHANNEL_CASES)
async def test_channel_webhook_missing_signature_returns_400(
    channel_type: TenantChannelType,
    routing_address: str,
) -> None:
    boundary_store = InMemoryBoundaryPersistence()
    service = await _service_with_channel(
        boundary_store=boundary_store,
        channel_type=channel_type,
        routing_address=routing_address,
    )
    timestamp = datetime.now(timezone.utc)
    body = _body(
        channel_type=channel_type,
        routing_address=routing_address,
        timestamp=timestamp,
        nonce=f"{channel_type.value}-missing",
    )

    with pytest.raises(TicketIngressRejected) as exc_info:
        await service.process_channel_webhook(
            channel_type=channel_type.value,
            body=body,
            headers=_missing_signature_headers(
                channel_type=channel_type,
                timestamp=timestamp,
                nonce=f"{channel_type.value}-missing",
            ),
            raw_body=_raw(body),
            content_type="application/json",
        )

    assert exc_info.value.code == "missing_signature"
    assert exc_info.value.status_code == 400
    page = await boundary_store.list_ingress(BoundaryIngressQuery())
    assert page.total == 0


async def _service_with_channel(
    *,
    boundary_store: InMemoryBoundaryPersistence,
    channel_type: TenantChannelType,
    routing_address: str,
) -> TicketIngressService:
    tenant_runtime = TenantConfigurationRuntime(
        repository=InMemoryTenantConfigurationRepository(),
        credential_encryptor=TenantCredentialEncryptor(
            platform_master_key=MASTER_KEY,
        ),
    )
    await tenant_runtime.configure_channel(
        tenant_id=TENANT_ID,
        channel_type=channel_type,
        routing_address=routing_address,
        credentials={"token": f"{channel_type.value}-token"},
        webhook_secret=_secret(channel_type),
        status=TenantChannelStatus.ACTIVE,
    )
    return TicketIngressService(
        persistence=boundary_store,
        session=_FakeSession(),  # type: ignore[arg-type]
        tenant_configuration_runtime=tenant_runtime,
    )


def _body(
    *,
    channel_type: TenantChannelType,
    routing_address: str,
    timestamp: datetime,
    nonce: str,
) -> dict[str, Any]:
    if channel_type is TenantChannelType.EMAIL:
        return {
            "message_id": nonce,
            "nonce": nonce,
            "to": routing_address,
            "text": "hello",
            "timestamp": timestamp.isoformat(),
        }
    if channel_type is TenantChannelType.WHATSAPP:
        return {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {
                                    "phone_number_id": routing_address
                                },
                                "messages": [
                                    {
                                        "id": nonce,
                                        "from": "15551234567",
                                        "timestamp": str(
                                            int(timestamp.timestamp())
                                        ),
                                        "type": "text",
                                        "text": {"body": "hello"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }
    if channel_type is TenantChannelType.SHULEX:
        return {
            "event_id": nonce,
            "nonce": nonce,
            "shop_id": routing_address,
            "message": "hello",
            "timestamp": timestamp.isoformat(),
        }
    if channel_type is TenantChannelType.LARK:
        return {
            "header": {
                "event_id": nonce,
                "app_id": routing_address,
                "event_type": "im.message.receive_v1",
                "create_time": str(int(timestamp.timestamp() * 1000)),
            },
            "event": {
                "message": {
                    "message_id": nonce,
                    "chat_id": "oc_chat",
                    "content": "{\"text\":\"hello\"}",
                }
            },
        }
    raise AssertionError(channel_type)


def _signed_headers(
    *,
    channel_type: TenantChannelType,
    secret: str,
    raw_body: bytes,
    timestamp: datetime,
    nonce: str,
) -> dict[str, str]:
    if channel_type is TenantChannelType.LARK:
        timestamp_value = str(int(timestamp.timestamp()))
        digest = hmac.new(
            secret.encode("utf-8"),
            timestamp_value.encode("utf-8")
            + nonce.encode("utf-8")
            + raw_body,
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-Lark-Request-Timestamp": timestamp_value,
            "X-Lark-Request-Nonce": nonce,
            "X-Lark-Signature": f"sha256={digest}",
        }
    digest = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    if channel_type is TenantChannelType.WHATSAPP:
        return {"X-Hub-Signature-256": f"sha256={digest}"}
    if channel_type is TenantChannelType.SHULEX:
        return {"X-Shulex-Signature": f"sha256={digest}"}
    return {"X-Operious-Signature": f"sha256={digest}"}


def _invalid_signature_headers(
    *,
    channel_type: TenantChannelType,
    timestamp: datetime,
    nonce: str,
) -> dict[str, str]:
    if channel_type is TenantChannelType.LARK:
        return {
            "X-Lark-Request-Timestamp": str(int(timestamp.timestamp())),
            "X-Lark-Request-Nonce": nonce,
            "X-Lark-Signature": "sha256=bad",
        }
    if channel_type is TenantChannelType.WHATSAPP:
        return {"X-Hub-Signature-256": "sha256=bad"}
    if channel_type is TenantChannelType.SHULEX:
        return {"X-Shulex-Signature": "sha256=bad"}
    return {"X-Operious-Signature": "sha256=bad"}


def _missing_signature_headers(
    *,
    channel_type: TenantChannelType,
    timestamp: datetime,
    nonce: str,
) -> dict[str, str]:
    if channel_type is TenantChannelType.LARK:
        return {
            "X-Lark-Request-Timestamp": str(int(timestamp.timestamp())),
            "X-Lark-Request-Nonce": nonce,
        }
    return {}


def _secret(channel_type: TenantChannelType) -> str:
    return f"{channel_type.value}-secret"


def _raw(body: Mapping[str, Any]) -> bytes:
    return json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
