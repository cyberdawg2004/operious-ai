"""Phase 2.5-F tenant-owned channel webhook adapters."""

from __future__ import annotations

import hashlib
import hmac
import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

import pytest

from app.boundary.adapters import canonical_channel_payload_keys
from app.boundary.enums import (
    BoundaryNormalizationStatus,
    BoundarySourceType,
)
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


MASTER_KEY = "phase-2-5-f-master-key-32-bytes-minimum"
TENANT_ID = "tenant-channel-alpha"
OTHER_TENANT_ID = "tenant-channel-beta"


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("channel_type", "routing_address", "body"),
    [
        (
            TenantChannelType.EMAIL,
            "support@example.com",
            {
                "message_id": "email-message-001",
                "to": "support@example.com",
                "from": "customer@example.net",
                "subject": "PowerCore support",
                "text": "My battery stopped charging.",
                "event_type": "message.received",
            },
        ),
        (
            TenantChannelType.WHATSAPP,
            "phone-number-123",
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "metadata": {
                                        "phone_number_id": "phone-number-123"
                                    },
                                    "messages": [
                                        {
                                            "id": "wamid.001",
                                            "from": "15551234567",
                                            "timestamp": "1779458400",
                                            "type": "text",
                                            "text": {
                                                "body": "My cable failed."
                                            },
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                ]
            },
        ),
        (
            TenantChannelType.SHULEX,
            "shop-42",
            {
                "event_id": "shulex-event-001",
                "shop_id": "shop-42",
                "conversation_id": "conversation-42",
                "customer_id": "customer-42",
                "subject": "Refund question",
                "message": "Can I return this charger?",
                "event_type": "message.created",
            },
        ),
        (
            TenantChannelType.LARK,
            "cli_a1b2c3",
            {
                "header": {
                    "event_id": "lark-event-001",
                    "app_id": "cli_a1b2c3",
                    "event_type": "im.message.receive_v1",
                    "create_time": "1779458400000",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_customer"}
                    },
                    "message": {
                        "message_id": "om_lark_message",
                        "chat_id": "oc_chat",
                        "content": "{\"text\":\"Need product help\"}",
                    },
                },
            },
        ),
    ],
)
async def test_channel_webhook_ingress_normalizes_to_common_envelope(
    channel_type: TenantChannelType,
    routing_address: str,
    body: Mapping[str, Any],
) -> None:
    boundary_store = InMemoryBoundaryPersistence()
    session = _FakeSession()
    service = await _service_with_channel(
        boundary_store=boundary_store,
        session=session,
        channel_type=channel_type,
        routing_address=routing_address,
        tenant_id=TENANT_ID,
        webhook_secret=f"{channel_type.value}-secret",
    )
    body = _with_fresh_timestamp(channel_type, body)
    raw_body = _raw(body)

    result = await service.process_channel_webhook(
        channel_type=channel_type.value,
        body=body,
        headers=_signed_headers(
            channel_type=channel_type,
            secret=f"{channel_type.value}-secret",
            raw_body=raw_body,
        ),
        raw_body=raw_body,
        content_type="application/json",
    )

    page = await boundary_store.list_ingress(
        BoundaryIngressQuery(),
        expected_tenant_id=TENANT_ID,
    )
    assert page.total == 1
    record = page.ingress[0]
    assert result.ingress_id == str(record.ingress_id)
    assert result.canonical_envelope_id == str(record.event_id)
    assert record.tenant_id == TENANT_ID
    assert record.normalization_status is BoundaryNormalizationStatus.OK
    assert record.source_type is _source_type(channel_type)
    assert set(record.canonical_payload) == canonical_channel_payload_keys()
    assert record.canonical_payload["channel"] == channel_type.value
    assert record.canonical_payload["to"] == routing_address
    assert "entry" not in record.canonical_payload
    assert "header" not in record.canonical_payload
    assert "shop_id" not in record.canonical_payload
    assert session.commits == 1


@pytest.mark.asyncio
async def test_channel_webhook_rejects_failed_signature() -> None:
    boundary_store = InMemoryBoundaryPersistence()
    service = await _service_with_channel(
        boundary_store=boundary_store,
        session=_FakeSession(),
        channel_type=TenantChannelType.EMAIL,
        routing_address="support@example.com",
        tenant_id=TENANT_ID,
        webhook_secret="email-secret",
    )
    body = {
        "message_id": "email-message-002",
        "to": "support@example.com",
        "text": "hello",
    }

    with pytest.raises(TicketIngressRejected) as exc_info:
        await service.process_channel_webhook(
            channel_type="email",
            body=body,
            headers={"X-Operious-Signature": "sha256=bad"},
            raw_body=_raw(body),
            content_type="application/json",
        )

    # Uniform rejection prevents route/tenant enumeration (#24).
    assert exc_info.value.code == "webhook_rejected"
    assert exc_info.value.status_code == 401
    page = await boundary_store.list_ingress(
        BoundaryIngressQuery(),
        expected_tenant_id=TENANT_ID,
    )
    assert page.total == 0


@pytest.mark.asyncio
async def test_channel_webhook_unknown_routing_does_not_persist() -> None:
    boundary_store = InMemoryBoundaryPersistence()
    service = await _service_with_channel(
        boundary_store=boundary_store,
        session=_FakeSession(),
        channel_type=TenantChannelType.EMAIL,
        routing_address="support@example.com",
        tenant_id=TENANT_ID,
        webhook_secret="email-secret",
    )
    body = {
        "message_id": "email-message-003",
        "to": "unknown@example.com",
        "text": "hello",
    }

    with pytest.raises(TicketIngressRejected) as exc_info:
        await service.process_channel_webhook(
            channel_type="email",
            body=body,
            headers=_signed_headers(
                channel_type=TenantChannelType.EMAIL,
                secret="email-secret",
                raw_body=_raw(body),
            ),
            raw_body=_raw(body),
            content_type="application/json",
        )

    # Unknown route returns the same opaque rejection as a bad signature (#24).
    assert exc_info.value.code == "webhook_rejected"
    assert exc_info.value.status_code == 401
    page = await boundary_store.list_ingress(BoundaryIngressQuery())
    assert page.total == 0


@pytest.mark.asyncio
async def test_channel_webhook_tenant_hint_mismatch_fails_closed() -> None:
    boundary_store = InMemoryBoundaryPersistence()
    service = await _service_with_channel(
        boundary_store=boundary_store,
        session=_FakeSession(),
        channel_type=TenantChannelType.EMAIL,
        routing_address="support@example.com",
        tenant_id=TENANT_ID,
        webhook_secret="email-secret",
    )
    body = {
        "message_id": "email-message-004",
        "to": "support@example.com",
        "text": "hello",
    }

    with pytest.raises(TicketIngressRejected) as exc_info:
        await service.process_channel_webhook(
            channel_type="email",
            body=body,
            headers=_signed_headers(
                channel_type=TenantChannelType.EMAIL,
                secret="email-secret",
                raw_body=_raw(body),
            ),
            raw_body=_raw(body),
            content_type="application/json",
            tenant_hint=OTHER_TENANT_ID,
        )

    # Tenant mismatch returns the same opaque rejection (#24).
    assert exc_info.value.code == "webhook_rejected"
    assert exc_info.value.status_code == 401
    page = await boundary_store.list_ingress(BoundaryIngressQuery())
    assert page.total == 0


@pytest.mark.asyncio
async def test_channel_webhook_does_not_expose_plaintext_credentials() -> None:
    boundary_store = InMemoryBoundaryPersistence()
    service = await _service_with_channel(
        boundary_store=boundary_store,
        session=_FakeSession(),
        channel_type=TenantChannelType.EMAIL,
        routing_address="support@example.com",
        tenant_id=TENANT_ID,
        webhook_secret="email-secret",
        credentials={"api_token": "plaintext-token-never-return"},
    )
    body = {
        "message_id": "email-message-005",
        "to": "support@example.com",
        "text": "hello",
    }
    body = _with_fresh_timestamp(TenantChannelType.EMAIL, body)

    result = await service.process_channel_webhook(
        channel_type="email",
        body=body,
        headers=_signed_headers(
            channel_type=TenantChannelType.EMAIL,
            secret="email-secret",
            raw_body=_raw(body),
        ),
        raw_body=_raw(body),
        content_type="application/json",
    )

    page = await boundary_store.list_ingress(
        BoundaryIngressQuery(),
        expected_tenant_id=TENANT_ID,
    )
    assert result.canonical_envelope_id == str(page.ingress[0].event_id)
    assert "plaintext-token-never-return" not in _jsonable_text(
        {
            "result": {
                "ingress_id": result.ingress_id,
                "canonical_envelope_id": result.canonical_envelope_id,
            },
            "canonical_payload": page.ingress[0].canonical_payload,
            "metadata": page.ingress[0].metadata,
        }
    )


@pytest.mark.asyncio
async def test_channel_webhook_identity_is_deterministic() -> None:
    boundary_store = InMemoryBoundaryPersistence()
    service = await _service_with_channel(
        boundary_store=boundary_store,
        session=_FakeSession(),
        channel_type=TenantChannelType.EMAIL,
        routing_address="support@example.com",
        tenant_id=TENANT_ID,
        webhook_secret="email-secret",
    )
    body = {
        "message_id": "email-message-006",
        "to": "support@example.com",
        "text": "hello",
    }
    body = _with_fresh_timestamp(TenantChannelType.EMAIL, body)
    headers = _signed_headers(
        channel_type=TenantChannelType.EMAIL,
        secret="email-secret",
        raw_body=_raw(body),
    )

    first = await service.process_channel_webhook(
        channel_type="email",
        body=body,
        headers=headers,
        raw_body=_raw(body),
        content_type="application/json",
    )
    second_store = InMemoryBoundaryPersistence()
    second_service = await _service_with_channel(
        boundary_store=second_store,
        session=_FakeSession(),
        channel_type=TenantChannelType.EMAIL,
        routing_address="support@example.com",
        tenant_id=TENANT_ID,
        webhook_secret="email-secret",
    )
    second = await second_service.process_channel_webhook(
        channel_type="email",
        body=body,
        headers=headers,
        raw_body=_raw(body),
        content_type="application/json",
    )

    assert second.ingress_id == first.ingress_id
    assert second.canonical_envelope_id == first.canonical_envelope_id
    page = await boundary_store.list_ingress(
        BoundaryIngressQuery(),
        expected_tenant_id=TENANT_ID,
    )
    assert page.total == 1


async def _service_with_channel(
    *,
    boundary_store: InMemoryBoundaryPersistence,
    session: _FakeSession,
    channel_type: TenantChannelType,
    routing_address: str,
    tenant_id: str,
    webhook_secret: str,
    credentials: Mapping[str, Any] | None = None,
) -> TicketIngressService:
    tenant_runtime = TenantConfigurationRuntime(
        repository=InMemoryTenantConfigurationRepository(),
        credential_encryptor=TenantCredentialEncryptor(
            platform_master_key=MASTER_KEY,
        ),
    )
    await tenant_runtime.configure_channel(
        tenant_id=tenant_id,
        channel_type=channel_type,
        routing_address=routing_address,
        credentials=credentials or {"token": f"{channel_type.value}-token"},
        webhook_secret=webhook_secret,
        status=TenantChannelStatus.ACTIVE,
    )
    return TicketIngressService(
        persistence=boundary_store,
        session=session,  # type: ignore[arg-type]
        tenant_configuration_runtime=tenant_runtime,
    )


def _signed_headers(
    *,
    channel_type: TenantChannelType,
    secret: str,
    raw_body: bytes,
) -> dict[str, str]:
    digest = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    if channel_type is TenantChannelType.WHATSAPP:
        return {"X-Hub-Signature-256": f"sha256={digest}"}
    if channel_type is TenantChannelType.SHULEX:
        return {"X-Shulex-Signature": f"sha256={digest}"}
    if channel_type is TenantChannelType.LARK:
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        nonce = "phase-2-5-f"
        lark_digest = hmac.new(
            secret.encode("utf-8"),
            timestamp.encode("utf-8") + nonce.encode("utf-8") + raw_body,
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-Lark-Request-Timestamp": timestamp,
            "X-Lark-Request-Nonce": nonce,
            "X-Lark-Signature": f"sha256={lark_digest}",
        }
    return {"X-Operious-Signature": f"sha256={digest}"}


def _with_fresh_timestamp(
    channel_type: TenantChannelType,
    body: Mapping[str, Any],
) -> dict[str, Any]:
    updated = deepcopy(dict(body))
    now = datetime.now(timezone.utc)
    if channel_type is TenantChannelType.EMAIL:
        updated["timestamp"] = now.isoformat()
    elif channel_type is TenantChannelType.WHATSAPP:
        value = updated["entry"][0]["changes"][0]["value"]
        value["messages"][0]["timestamp"] = str(int(now.timestamp()))
    elif channel_type is TenantChannelType.SHULEX:
        updated["timestamp"] = now.isoformat()
    elif channel_type is TenantChannelType.LARK:
        updated["header"]["create_time"] = str(int(now.timestamp() * 1000))
    return updated


def _raw(body: Mapping[str, Any]) -> bytes:
    return json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _source_type(channel_type: TenantChannelType) -> BoundarySourceType:
    if channel_type is TenantChannelType.EMAIL:
        return BoundarySourceType.EMAIL
    if channel_type is TenantChannelType.WHATSAPP:
        return BoundarySourceType.WHATSAPP
    if channel_type is TenantChannelType.SHULEX:
        return BoundarySourceType.SHULEX
    if channel_type is TenantChannelType.LARK:
        return BoundarySourceType.LARK
    raise AssertionError(channel_type)


def _jsonable_text(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)
