"""Webhook signing conformance tests for tenant channel adapters."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any, Mapping

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.boundary.persistence import PostgresBoundaryPersistence
from app.core.config import get_settings
from app.dependencies.services import get_ticket_ingress_service
from app.main import create_app
from app.services.ticket_ingress_service import TicketIngressService
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.db.models import TenantRow
from app.tenant.enums import TenantChannelStatus, TenantChannelType
from app.tenant.persistence import PostgresTenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]

TEST_WEBHOOK_SECRET = "test-secret-conformance-pr12"
_MASTER_KEY = "webhook-conformance-master-key-32-bytes"

_EMAIL_TENANT_ID = "conformance-email-tenant"
_EMAIL_ROUTE = "conf@operious.com"
_WHATSAPP_TENANT_ID = "conformance-wa-tenant"
_WHATSAPP_ROUTE = "+15550001234"
_SHULEX_TENANT_ID = "conformance-shulex-tenant"
_SHULEX_ROUTE = "shulex-conf-123"
_LARK_TENANT_ID = "conformance-lark-tenant"
_LARK_ROUTE = "lark-conf-bot-123"


class _NoRollbackSession:
    """Keep seeded rows visible across the webhook service routing reset."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def rollback(self) -> None:
        return None

    async def commit(self) -> None:
        await self._session.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


@pytest_asyncio.fixture
async def app_client(
    pg_seed_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("TENANT_CREDENTIAL_MASTER_KEY", _MASTER_KEY)
    get_settings.cache_clear()
    app = create_app()
    service_session = _NoRollbackSession(pg_seed_session)
    tenant_runtime = TenantConfigurationRuntime(
        repository=PostgresTenantConfigurationRepository(service_session),  # type: ignore[arg-type]
        credential_encryptor=TenantCredentialEncryptor(
            platform_master_key=_MASTER_KEY,
        ),
    )
    service = TicketIngressService(
        persistence=PostgresBoundaryPersistence(service_session),  # type: ignore[arg-type]
        session=service_session,  # type: ignore[arg-type]
        tenant_configuration_runtime=tenant_runtime,
    )

    def _override_service() -> TicketIngressService:
        return service

    app.dependency_overrides[get_ticket_ingress_service] = _override_service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client
    get_settings.cache_clear()


async def seed_channel_for_adapter(
    pg_seed_session: AsyncSession,
    tenant_id: str,
    channel_type: str,
    routing_address: str,
) -> None:
    await pg_seed_session.merge(TenantRow(tenant_id=tenant_id))
    await pg_seed_session.flush()
    runtime = TenantConfigurationRuntime(
        repository=PostgresTenantConfigurationRepository(pg_seed_session),
        credential_encryptor=TenantCredentialEncryptor(
            platform_master_key=_MASTER_KEY,
        ),
    )
    parsed_channel_type = TenantChannelType(channel_type)
    await runtime.configure_channel(
        tenant_id=tenant_id,
        channel_type=parsed_channel_type,
        routing_address=routing_address,
        credentials={"token": f"{channel_type}-token"},
        webhook_secret=TEST_WEBHOOK_SECRET,
        status=TenantChannelStatus.ACTIVE,
    )
    await pg_seed_session.flush()


def sign_raw_body(secret: str, body: bytes) -> str:
    return hmac.new(
        secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()


def sign_lark(
    secret: str,
    timestamp: str,
    nonce: str,
    body: bytes,
) -> str:
    return hmac.new(
        secret.encode(),
        timestamp.encode() + nonce.encode() + body,
        hashlib.sha256,
    ).hexdigest()


def fresh_timestamp() -> str:
    return str(int(time.time()))


def stale_timestamp() -> str:
    return str(int(time.time()) - 400)


class TestEmailWebhookSigningConformance:
    @pytest.fixture
    def pg_tenant_id(self) -> str:
        return _EMAIL_TENANT_ID

    @pytest.mark.asyncio
    async def test_email_valid_signature_accepted(
        self,
        pg_seed_session: AsyncSession,
        pg_tenant_id: str,
        app_client: httpx.AsyncClient,
    ) -> None:
        await seed_channel_for_adapter(
            pg_seed_session, pg_tenant_id, "email", _EMAIL_ROUTE
        )
        ts = fresh_timestamp()
        nonce = _nonce("email-valid")
        body = _raw(build_email_body(_EMAIL_ROUTE, ts, nonce))
        sig = sign_raw_body(TEST_WEBHOOK_SECRET, body)

        response = await _post_webhook(
            app_client,
            "email",
            tenant_id=pg_tenant_id,
            body=body,
            headers={
                "X-Operious-Signature": sig,
                "X-Operious-Webhook-Timestamp": ts,
            },
        )

        assert response.status_code == 200, response.text

    @pytest.mark.asyncio
    async def test_email_invalid_signature_rejected(
        self,
        pg_seed_session: AsyncSession,
        pg_tenant_id: str,
        app_client: httpx.AsyncClient,
    ) -> None:
        await seed_channel_for_adapter(
            pg_seed_session, pg_tenant_id, "email", _EMAIL_ROUTE
        )
        ts = fresh_timestamp()
        nonce = _nonce("email-invalid")
        body = _raw(build_email_body(_EMAIL_ROUTE, ts, nonce))
        sig = _invalid_signature(sign_raw_body(TEST_WEBHOOK_SECRET, body))

        response = await _post_webhook(
            app_client,
            "email",
            tenant_id=pg_tenant_id,
            body=body,
            headers={
                "X-Operious-Signature": sig,
                "X-Operious-Webhook-Timestamp": ts,
            },
        )

        assert response.status_code == 401, response.text

    @pytest.mark.asyncio
    async def test_email_missing_signature_rejected(
        self,
        pg_seed_session: AsyncSession,
        pg_tenant_id: str,
        app_client: httpx.AsyncClient,
    ) -> None:
        await seed_channel_for_adapter(
            pg_seed_session, pg_tenant_id, "email", _EMAIL_ROUTE
        )
        ts = fresh_timestamp()
        nonce = _nonce("email-missing")
        body = _raw(build_email_body(_EMAIL_ROUTE, ts, nonce))

        response = await _post_webhook(
            app_client,
            "email",
            tenant_id=pg_tenant_id,
            body=body,
            headers={"X-Operious-Webhook-Timestamp": ts},
        )

        assert response.status_code == 401, response.text

    @pytest.mark.asyncio
    async def test_email_stale_timestamp_rejected(
        self,
        pg_seed_session: AsyncSession,
        pg_tenant_id: str,
        app_client: httpx.AsyncClient,
    ) -> None:
        await seed_channel_for_adapter(
            pg_seed_session, pg_tenant_id, "email", _EMAIL_ROUTE
        )
        ts = stale_timestamp()
        nonce = _nonce("email-stale")
        body = _raw(build_email_body(_EMAIL_ROUTE, ts, nonce))
        sig = sign_raw_body(TEST_WEBHOOK_SECRET, body)

        response = await _post_webhook(
            app_client,
            "email",
            tenant_id=pg_tenant_id,
            body=body,
            headers={
                "X-Operious-Signature": sig,
                "X-Operious-Webhook-Timestamp": ts,
            },
        )

        assert response.status_code == 401, response.text


class TestWhatsAppWebhookSigningConformance:
    @pytest.fixture
    def pg_tenant_id(self) -> str:
        return _WHATSAPP_TENANT_ID

    @pytest.mark.asyncio
    async def test_whatsapp_valid_signature_accepted(
        self,
        pg_seed_session: AsyncSession,
        pg_tenant_id: str,
        app_client: httpx.AsyncClient,
    ) -> None:
        await seed_channel_for_adapter(
            pg_seed_session, pg_tenant_id, "whatsapp", _WHATSAPP_ROUTE
        )
        ts = fresh_timestamp()
        nonce = _nonce("whatsapp-valid")
        body = _raw(build_whatsapp_body(_WHATSAPP_ROUTE, ts, nonce))
        sig = sign_raw_body(TEST_WEBHOOK_SECRET, body)

        response = await _post_webhook(
            app_client,
            "whatsapp",
            tenant_id=pg_tenant_id,
            body=body,
            headers={
                "X-Hub-Signature-256": sig,
                "X-Operious-Webhook-Timestamp": ts,
            },
        )

        assert response.status_code == 200, response.text

    @pytest.mark.asyncio
    async def test_whatsapp_invalid_signature_rejected(
        self,
        pg_seed_session: AsyncSession,
        pg_tenant_id: str,
        app_client: httpx.AsyncClient,
    ) -> None:
        await seed_channel_for_adapter(
            pg_seed_session, pg_tenant_id, "whatsapp", _WHATSAPP_ROUTE
        )
        ts = fresh_timestamp()
        nonce = _nonce("whatsapp-invalid")
        body = _raw(build_whatsapp_body(_WHATSAPP_ROUTE, ts, nonce))
        sig = _invalid_signature(sign_raw_body(TEST_WEBHOOK_SECRET, body))

        response = await _post_webhook(
            app_client,
            "whatsapp",
            tenant_id=pg_tenant_id,
            body=body,
            headers={
                "X-Hub-Signature-256": sig,
                "X-Operious-Webhook-Timestamp": ts,
            },
        )

        assert response.status_code == 401, response.text

    @pytest.mark.asyncio
    async def test_whatsapp_missing_signature_rejected(
        self,
        pg_seed_session: AsyncSession,
        pg_tenant_id: str,
        app_client: httpx.AsyncClient,
    ) -> None:
        await seed_channel_for_adapter(
            pg_seed_session, pg_tenant_id, "whatsapp", _WHATSAPP_ROUTE
        )
        ts = fresh_timestamp()
        nonce = _nonce("whatsapp-missing")
        body = _raw(build_whatsapp_body(_WHATSAPP_ROUTE, ts, nonce))

        response = await _post_webhook(
            app_client,
            "whatsapp",
            tenant_id=pg_tenant_id,
            body=body,
            headers={"X-Operious-Webhook-Timestamp": ts},
        )

        assert response.status_code == 401, response.text

    @pytest.mark.asyncio
    async def test_whatsapp_stale_timestamp_rejected(
        self,
        pg_seed_session: AsyncSession,
        pg_tenant_id: str,
        app_client: httpx.AsyncClient,
    ) -> None:
        await seed_channel_for_adapter(
            pg_seed_session, pg_tenant_id, "whatsapp", _WHATSAPP_ROUTE
        )
        ts = stale_timestamp()
        nonce = _nonce("whatsapp-stale")
        body = _raw(build_whatsapp_body(_WHATSAPP_ROUTE, ts, nonce))
        sig = sign_raw_body(TEST_WEBHOOK_SECRET, body)

        response = await _post_webhook(
            app_client,
            "whatsapp",
            tenant_id=pg_tenant_id,
            body=body,
            headers={
                "X-Hub-Signature-256": sig,
                "X-Operious-Webhook-Timestamp": ts,
            },
        )

        assert response.status_code == 401, response.text


class TestShulexWebhookSigningConformance:
    @pytest.fixture
    def pg_tenant_id(self) -> str:
        return _SHULEX_TENANT_ID

    @pytest.mark.asyncio
    async def test_shulex_valid_signature_accepted(
        self,
        pg_seed_session: AsyncSession,
        pg_tenant_id: str,
        app_client: httpx.AsyncClient,
    ) -> None:
        await seed_channel_for_adapter(
            pg_seed_session, pg_tenant_id, "shulex", _SHULEX_ROUTE
        )
        ts = fresh_timestamp()
        nonce = _nonce("shulex-valid")
        body = _raw(build_shulex_body(_SHULEX_ROUTE, ts, nonce))
        sig = sign_raw_body(TEST_WEBHOOK_SECRET, body)

        response = await _post_webhook(
            app_client,
            "shulex",
            tenant_id=pg_tenant_id,
            body=body,
            headers={
                "X-Shulex-Signature": sig,
                "X-Operious-Webhook-Timestamp": ts,
            },
        )

        assert response.status_code == 200, response.text

    @pytest.mark.asyncio
    async def test_shulex_invalid_signature_rejected(
        self,
        pg_seed_session: AsyncSession,
        pg_tenant_id: str,
        app_client: httpx.AsyncClient,
    ) -> None:
        await seed_channel_for_adapter(
            pg_seed_session, pg_tenant_id, "shulex", _SHULEX_ROUTE
        )
        ts = fresh_timestamp()
        nonce = _nonce("shulex-invalid")
        body = _raw(build_shulex_body(_SHULEX_ROUTE, ts, nonce))
        sig = _invalid_signature(sign_raw_body(TEST_WEBHOOK_SECRET, body))

        response = await _post_webhook(
            app_client,
            "shulex",
            tenant_id=pg_tenant_id,
            body=body,
            headers={
                "X-Shulex-Signature": sig,
                "X-Operious-Webhook-Timestamp": ts,
            },
        )

        assert response.status_code == 401, response.text

    @pytest.mark.asyncio
    async def test_shulex_missing_signature_rejected(
        self,
        pg_seed_session: AsyncSession,
        pg_tenant_id: str,
        app_client: httpx.AsyncClient,
    ) -> None:
        await seed_channel_for_adapter(
            pg_seed_session, pg_tenant_id, "shulex", _SHULEX_ROUTE
        )
        ts = fresh_timestamp()
        nonce = _nonce("shulex-missing")
        body = _raw(build_shulex_body(_SHULEX_ROUTE, ts, nonce))

        response = await _post_webhook(
            app_client,
            "shulex",
            tenant_id=pg_tenant_id,
            body=body,
            headers={"X-Operious-Webhook-Timestamp": ts},
        )

        assert response.status_code == 401, response.text

    @pytest.mark.asyncio
    async def test_shulex_stale_timestamp_rejected(
        self,
        pg_seed_session: AsyncSession,
        pg_tenant_id: str,
        app_client: httpx.AsyncClient,
    ) -> None:
        await seed_channel_for_adapter(
            pg_seed_session, pg_tenant_id, "shulex", _SHULEX_ROUTE
        )
        ts = stale_timestamp()
        nonce = _nonce("shulex-stale")
        body = _raw(build_shulex_body(_SHULEX_ROUTE, ts, nonce))
        sig = sign_raw_body(TEST_WEBHOOK_SECRET, body)

        response = await _post_webhook(
            app_client,
            "shulex",
            tenant_id=pg_tenant_id,
            body=body,
            headers={
                "X-Shulex-Signature": sig,
                "X-Operious-Webhook-Timestamp": ts,
            },
        )

        assert response.status_code == 401, response.text


class TestLarkWebhookSigningConformance:
    @pytest.fixture
    def pg_tenant_id(self) -> str:
        return _LARK_TENANT_ID

    @pytest.mark.asyncio
    async def test_lark_valid_signature_accepted(
        self,
        pg_seed_session: AsyncSession,
        pg_tenant_id: str,
        app_client: httpx.AsyncClient,
    ) -> None:
        await seed_channel_for_adapter(
            pg_seed_session, pg_tenant_id, "lark", _LARK_ROUTE
        )
        ts = fresh_timestamp()
        nonce = _nonce("lark-valid")
        body = _raw(build_lark_body(_LARK_ROUTE, ts, nonce))
        sig = sign_lark(TEST_WEBHOOK_SECRET, ts, nonce, body)

        response = await _post_webhook(
            app_client,
            "lark",
            tenant_id=pg_tenant_id,
            body=body,
            headers={
                "X-Lark-Signature": sig,
                "X-Lark-Request-Timestamp": ts,
                "X-Lark-Request-Nonce": nonce,
            },
        )

        assert response.status_code == 200, response.text

    @pytest.mark.asyncio
    async def test_lark_invalid_signature_rejected(
        self,
        pg_seed_session: AsyncSession,
        pg_tenant_id: str,
        app_client: httpx.AsyncClient,
    ) -> None:
        await seed_channel_for_adapter(
            pg_seed_session, pg_tenant_id, "lark", _LARK_ROUTE
        )
        ts = fresh_timestamp()
        nonce = _nonce("lark-invalid")
        body = _raw(build_lark_body(_LARK_ROUTE, ts, nonce))
        sig = _invalid_signature(sign_lark(TEST_WEBHOOK_SECRET, ts, nonce, body))

        response = await _post_webhook(
            app_client,
            "lark",
            tenant_id=pg_tenant_id,
            body=body,
            headers={
                "X-Lark-Signature": sig,
                "X-Lark-Request-Timestamp": ts,
                "X-Lark-Request-Nonce": nonce,
            },
        )

        assert response.status_code == 401, response.text

    @pytest.mark.asyncio
    async def test_lark_missing_signature_rejected(
        self,
        pg_seed_session: AsyncSession,
        pg_tenant_id: str,
        app_client: httpx.AsyncClient,
    ) -> None:
        await seed_channel_for_adapter(
            pg_seed_session, pg_tenant_id, "lark", _LARK_ROUTE
        )
        ts = fresh_timestamp()
        nonce = _nonce("lark-missing")
        body = _raw(build_lark_body(_LARK_ROUTE, ts, nonce))

        response = await _post_webhook(
            app_client,
            "lark",
            tenant_id=pg_tenant_id,
            body=body,
            headers={
                "X-Lark-Request-Timestamp": ts,
                "X-Lark-Request-Nonce": nonce,
            },
        )

        assert response.status_code == 401, response.text

    @pytest.mark.asyncio
    async def test_lark_stale_timestamp_rejected(
        self,
        pg_seed_session: AsyncSession,
        pg_tenant_id: str,
        app_client: httpx.AsyncClient,
    ) -> None:
        await seed_channel_for_adapter(
            pg_seed_session, pg_tenant_id, "lark", _LARK_ROUTE
        )
        ts = stale_timestamp()
        nonce = _nonce("lark-stale")
        body = _raw(build_lark_body(_LARK_ROUTE, ts, nonce))
        sig = sign_lark(TEST_WEBHOOK_SECRET, ts, nonce, body)

        response = await _post_webhook(
            app_client,
            "lark",
            tenant_id=pg_tenant_id,
            body=body,
            headers={
                "X-Lark-Signature": sig,
                "X-Lark-Request-Timestamp": ts,
                "X-Lark-Request-Nonce": nonce,
            },
        )

        assert response.status_code == 401, response.text


def build_email_body(
    routing_address: str,
    timestamp: str,
    nonce: str,
) -> dict[str, Any]:
    return {
        "message_id": nonce,
        "nonce": nonce,
        "to": routing_address,
        "text": "hello",
        "timestamp": timestamp,
    }


def build_whatsapp_body(
    routing_address: str,
    timestamp: str,
    nonce: str,
) -> dict[str, Any]:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {
                                "phone_number_id": routing_address,
                            },
                            "messages": [
                                {
                                    "id": nonce,
                                    "from": "15551234567",
                                    "timestamp": timestamp,
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


def build_shulex_body(
    routing_address: str,
    timestamp: str,
    nonce: str,
) -> dict[str, Any]:
    return {
        "event_id": nonce,
        "nonce": nonce,
        "shop_id": routing_address,
        "message": "hello",
        "timestamp": timestamp,
    }


def build_lark_body(
    routing_address: str,
    timestamp: str,
    nonce: str,
) -> dict[str, Any]:
    return {
        "header": {
            "event_id": nonce,
            "app_id": routing_address,
            "event_type": "im.message.receive_v1",
            "create_time": str(int(timestamp) * 1000),
        },
        "event": {
            "message": {
                "message_id": nonce,
                "chat_id": "oc_chat",
                "content": "{\"text\":\"hello\"}",
            }
        },
    }


async def _post_webhook(
    client: httpx.AsyncClient,
    channel_type: str,
    *,
    tenant_id: str,
    body: bytes,
    headers: Mapping[str, str],
) -> httpx.Response:
    merged_headers = {
        "Content-Type": "application/json",
        "X-Tenant-ID": tenant_id,
        "X-Principal-ID": "webhook-conformance",
        **dict(headers),
    }
    return await client.post(
        f"/api/v1/boundary/translation/channels/{channel_type}/webhook",
        content=body,
        headers=merged_headers,
    )


def _raw(body: Mapping[str, Any]) -> bytes:
    return json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _nonce(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def _invalid_signature(signature: str) -> str:
    return "invalid" + signature[7:]
