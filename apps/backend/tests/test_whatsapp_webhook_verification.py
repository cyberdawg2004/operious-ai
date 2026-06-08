from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.params import Query as QueryParam

from app.api.v1.routers.ingress import verify_channel_webhook_ingress
from app.boundary.persistence import InMemoryBoundaryPersistence
from app.services.ticket_ingress_service import (
    TicketIngressRejected,
    TicketIngressService,
)
from app.tenant.enums import TenantChannelStatus, TenantChannelType
from app.tenant.identity import derive_channel_configuration_id
from app.tenant.persistence import (
    TenantChannelConfigurationRecord,
    TenantWebhookRoutingSecretRecord,
)

TENANT_ID = "tenant-wa-verification"
PHONE_NUMBER_ID = "wa-phone-123"
VERIFY_TOKEN = "verify-token-123"
NOW = datetime(2026, 6, 8, tzinfo=timezone.utc)


class _Session:
    async def rollback(self) -> None:
        return None


class _TenantRuntime:
    async def resolve_webhook_routing_secret(
        self,
        *,
        channel_type: TenantChannelType,
        routing_address: str,
    ) -> TenantWebhookRoutingSecretRecord | None:
        if (
            channel_type is not TenantChannelType.WHATSAPP
            or routing_address != PHONE_NUMBER_ID
        ):
            return None
        return TenantWebhookRoutingSecretRecord(
            tenant_id=TENANT_ID,
            config_id=derive_channel_configuration_id(
                tenant_id=TENANT_ID,
                channel_type=TenantChannelType.WHATSAPP,
            ),
            channel_type=TenantChannelType.WHATSAPP,
            routing_address=PHONE_NUMBER_ID,
            webhook_secret="post-signing-secret",
        )

    async def resolve_active_channel_for_routing_address(
        self,
        *,
        channel_type: TenantChannelType,
        routing_address: str,
        expected_tenant_id: str | None = None,
    ) -> TenantChannelConfigurationRecord | None:
        if (
            channel_type is not TenantChannelType.WHATSAPP
            or routing_address != PHONE_NUMBER_ID
            or expected_tenant_id != TENANT_ID
        ):
            return None
        return TenantChannelConfigurationRecord(
            config_id=derive_channel_configuration_id(
                tenant_id=TENANT_ID,
                channel_type=TenantChannelType.WHATSAPP,
            ),
            tenant_id=TENANT_ID,
            channel_type=TenantChannelType.WHATSAPP,
            status=TenantChannelStatus.ACTIVE,
            routing_address=PHONE_NUMBER_ID,
            credentials_enc=b"",
            webhook_secret="post-signing-secret",
            verified_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )

    async def load_channel_credentials(
        self,
        *,
        tenant_id: str,
        channel_type: TenantChannelType,
    ) -> dict[str, Any]:
        assert tenant_id == TENANT_ID
        assert channel_type is TenantChannelType.WHATSAPP
        return {"webhook_verify_token": VERIFY_TOKEN}


@pytest.mark.asyncio
async def test_whatsapp_get_verification_valid_token_echoes_challenge() -> None:
    service = _service()

    challenge = await service.verify_channel_webhook(
        channel_type="whatsapp",
        mode="subscribe",
        verify_token=VERIFY_TOKEN,
        challenge="challenge-42",
        phone_number_id=PHONE_NUMBER_ID,
    )

    assert challenge == "challenge-42"


@pytest.mark.asyncio
async def test_whatsapp_get_verification_wrong_token_returns_403() -> None:
    service = _service()

    with pytest.raises(TicketIngressRejected) as exc_info:
        await service.verify_channel_webhook(
            channel_type="whatsapp",
            mode="subscribe",
            verify_token="wrong-token",
            challenge="challenge-42",
            phone_number_id=PHONE_NUMBER_ID,
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_whatsapp_get_verification_route_uses_meta_query_shape() -> None:
    signature = inspect.signature(verify_channel_webhook_ingress)

    assert isinstance(signature.parameters["hub_mode"].default, QueryParam)
    assert signature.parameters["hub_mode"].default.alias == "hub.mode"
    assert isinstance(
        signature.parameters["hub_verify_token"].default,
        QueryParam,
    )
    assert (
        signature.parameters["hub_verify_token"].default.alias
        == "hub.verify_token"
    )
    assert isinstance(signature.parameters["hub_challenge"].default, QueryParam)
    assert signature.parameters["hub_challenge"].default.alias == "hub.challenge"

    response = await verify_channel_webhook_ingress(
        channel_type="whatsapp",
        hub_mode="subscribe",
        hub_verify_token=VERIFY_TOKEN,
        hub_challenge="challenge-from-meta",
        phone_number_id=PHONE_NUMBER_ID,
        expected_tenant_id=None,
        service=_service(),
    )

    assert response.status_code == 200
    assert response.body == b"challenge-from-meta"
    assert response.media_type == "text/plain"


def _service() -> TicketIngressService:
    return TicketIngressService(
        persistence=InMemoryBoundaryPersistence(),
        session=_Session(),  # type: ignore[arg-type]
        tenant_configuration_runtime=_TenantRuntime(),  # type: ignore[arg-type]
    )
