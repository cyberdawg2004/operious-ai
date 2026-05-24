"""Phase F webhook freshness enforcement."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
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

MASTER_KEY = "phase-f-freshness-master-key-32-bytes-min"
TENANT_ID = "tenant-phase-f-freshness"


class _FakeSession:
    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("channel_type", "routing_address"),
    [
        (TenantChannelType.EMAIL, "support@example.com"),
        (TenantChannelType.WHATSAPP, "phone-number-123"),
        (TenantChannelType.SHULEX, "shop-42"),
        (TenantChannelType.LARK, "cli_a1b2c3"),
    ],
)
async def test_webhook_with_stale_timestamp_rejected(
    channel_type: TenantChannelType,
    routing_address: str,
) -> None:
    boundary_store = InMemoryBoundaryPersistence()
    service = await _service_with_channel(
        boundary_store=boundary_store,
        channel_type=channel_type,
        routing_address=routing_address,
        webhook_secret=f"{channel_type.value}-secret",
    )
    timestamp = datetime.now(timezone.utc) - timedelta(minutes=10)
    body = _body(
        channel_type=channel_type,
        routing_address=routing_address,
        timestamp=timestamp,
    )
    raw_body = _raw(body)

    with pytest.raises(TicketIngressRejected) as exc_info:
        await service.process_channel_webhook(
            channel_type=channel_type.value,
            body=body,
            headers=_signed_headers(
                channel_type=channel_type,
                secret=f"{channel_type.value}-secret",
                raw_body=raw_body,
                timestamp=timestamp,
            ),
            raw_body=raw_body,
            content_type="application/json",
        )

    assert exc_info.value.code == "stale_webhook_timestamp"
    assert exc_info.value.status_code == 401
    page = await boundary_store.list_ingress(BoundaryIngressQuery())
    assert page.total == 0


async def _service_with_channel(
    *,
    boundary_store: InMemoryBoundaryPersistence,
    channel_type: TenantChannelType,
    routing_address: str,
    webhook_secret: str,
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
        webhook_secret=webhook_secret,
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
) -> dict[str, Any]:
    if channel_type is TenantChannelType.EMAIL:
        return {
            "message_id": "email-stale-001",
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
                                        "id": "wamid-stale-001",
                                        "from": "15551234567",
                                        "timestamp": str(int(timestamp.timestamp())),
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
            "event_id": "shulex-stale-001",
            "shop_id": routing_address,
            "message": "hello",
            "timestamp": timestamp.isoformat(),
        }
    if channel_type is TenantChannelType.LARK:
        return {
            "header": {
                "event_id": "lark-stale-001",
                "app_id": routing_address,
                "event_type": "im.message.receive_v1",
                "create_time": str(int(timestamp.timestamp() * 1000)),
            },
            "event": {
                "message": {
                    "message_id": "om_lark_stale",
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
        timestamp_value = str(int(timestamp.timestamp()))
        nonce = "phase-f-stale-nonce"
        lark_digest = hmac.new(
            secret.encode("utf-8"),
            timestamp_value.encode("utf-8")
            + nonce.encode("utf-8")
            + raw_body,
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-Lark-Request-Timestamp": timestamp_value,
            "X-Lark-Request-Nonce": nonce,
            "X-Lark-Signature": f"sha256={lark_digest}",
        }
    return {"X-Operious-Signature": f"sha256={digest}"}


def _raw(body: Mapping[str, Any]) -> bytes:
    return json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
