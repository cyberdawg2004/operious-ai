"""Phase 2.5-A tenant configuration endpoint tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import VerifiedIdentity
from app.auth.providers import StaticTokenProvider
from app.core.config import get_settings
from app.dependencies.authority import (
    TENANT_CONFIG_DOMAIN_WRITE_CAPABILITIES,
    TENANT_CONNECTOR_READ_CAPABILITY,
)
from app.dependencies.database import get_db_session
from app.main import create_app
from app.tenant.db.models import ConnectorConfigRow, TenantRow
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]

_MASTER_KEY = "tenant-config-router-master-key-material-32-bytes"


@pytest.fixture
def pg_tenant_id() -> str:
    return "tenant-acme"


@pytest_asyncio.fixture
async def tenant_client(
    pg_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("TENANT_CREDENTIAL_MASTER_KEY", _MASTER_KEY)
    monkeypatch.setenv("TENANT_CONFIG_ALLOW_SELF_APPROVAL", "true")
    get_settings.cache_clear()
    provider = StaticTokenProvider(
        tokens={
            "tenant-acme-admin": VerifiedIdentity(
                tenant_id="tenant-acme",
                principal_id="principal-a",
                capabilities=frozenset(TENANT_CONFIG_DOMAIN_WRITE_CAPABILITIES),
            ),
            "tenant-acme-reader": VerifiedIdentity(
                tenant_id="tenant-acme",
                principal_id="principal-reader",
                capabilities=frozenset({TENANT_CONNECTOR_READ_CAPABILITY}),
            ),
            "tenant-acme-empty": VerifiedIdentity(
                tenant_id="tenant-acme",
                principal_id="principal-empty",
                capabilities=frozenset(),
            ),
            "tenant-other-admin": VerifiedIdentity(
                tenant_id="tenant-other",
                principal_id="principal-a",
                capabilities=frozenset(TENANT_CONFIG_DOMAIN_WRITE_CAPABILITIES),
            ),
            "tenant-other-reader": VerifiedIdentity(
                tenant_id="tenant-other",
                principal_id="principal-reader",
                capabilities=frozenset({TENANT_CONNECTOR_READ_CAPABILITY}),
            ),
        }
    )
    app = create_app(auth_provider=provider)

    async def _override() -> AsyncIterator[AsyncSession]:
        yield pg_session

    app.dependency_overrides[get_db_session] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        yield client
    get_settings.cache_clear()


def _headers(tenant: str = "tenant-acme", role: str = "admin") -> dict[str, str]:
    return {"Authorization": f"Bearer {tenant}-{role}"}


@pytest.mark.asyncio
async def test_channel_endpoint_redacts_credentials(
    tenant_client: httpx.AsyncClient,
) -> None:
    response = await tenant_client.post(
        "/api/v1/tenant/channels",
        headers=_headers(),
        json={
            "channel_type": "email",
            "routing_address": "support@example.com",
            "credentials": {"api_key": "secret-api-key"},
            "webhook_secret": "webhook-secret",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "config_id",
        "channel_type",
        "routing_address",
        "status",
        "verified_at",
        "credential_rotated_at",
        "credential_rotation_expires_at",
    }
    assert "secret-api-key" not in response.text
    assert "webhook-secret" not in response.text

    listed = await tenant_client.get(
        "/api/v1/tenant/channels",
        headers=_headers(),
    )
    assert listed.status_code == 200
    assert "secret-api-key" not in listed.text
    assert listed.json()["total"] == 1


@pytest.mark.asyncio
async def test_channel_point_update_and_verify_are_tenant_scoped(
    tenant_client: httpx.AsyncClient,
) -> None:
    created = await tenant_client.post(
        "/api/v1/tenant/channels",
        headers=_headers("tenant-acme"),
        json={
            "channel_type": "whatsapp",
            "routing_address": "+15550001000",
            "credentials": {"token": "secret-token"},
            "webhook_secret": "webhook-secret",
        },
    )
    config_id = created.json()["config_id"]

    cross = await tenant_client.put(
        f"/api/v1/tenant/channels/{config_id}",
        headers=_headers("tenant-other"),
        json={"routing_address": "+15550009999"},
    )
    assert cross.status_code == 404

    updated = await tenant_client.put(
        f"/api/v1/tenant/channels/{config_id}",
        headers=_headers("tenant-acme"),
        json={"routing_address": "+15550001111", "status": "paused"},
    )
    assert updated.status_code == 200
    assert updated.json()["routing_address"] == "+15550001111"
    assert updated.json()["status"] == "paused"

    verified = await tenant_client.post(
        f"/api/v1/tenant/channels/{config_id}/verify",
        headers=_headers("tenant-acme"),
    )
    assert verified.status_code == 200
    assert verified.json()["status"] == "active"
    assert verified.json()["verified_at"] is not None


@pytest.mark.asyncio
async def test_connector_config_read_is_tenant_scoped(
    pg_session: AsyncSession,
    tenant_client: httpx.AsyncClient,
) -> None:
    await _seed_connector(pg_session, tool_name="refund.visibility")

    own = await tenant_client.get(
        "/api/v1/tenant/connectors/refund.visibility",
        headers=_headers("tenant-acme", "reader"),
    )
    cross = await tenant_client.get(
        "/api/v1/tenant/connectors/refund.visibility",
        headers=_headers("tenant-other", "reader"),
    )

    assert own.status_code == 200
    assert own.json()["total"] == 1
    assert cross.status_code == 404
    assert "tenant_connector_configuration_not_found" in cross.text


@pytest.mark.asyncio
async def test_connector_config_read_requires_connector_read_capability(
    pg_session: AsyncSession,
    tenant_client: httpx.AsyncClient,
) -> None:
    await _seed_connector(pg_session, tool_name="refund.capability")

    denied = await tenant_client.get(
        "/api/v1/tenant/connectors",
        headers=_headers("tenant-acme", "empty"),
    )
    allowed = await tenant_client.get(
        "/api/v1/tenant/connectors",
        headers=_headers("tenant-acme", "reader"),
    )

    assert denied.status_code == 403
    assert TENANT_CONNECTOR_READ_CAPABILITY in denied.text
    assert allowed.status_code == 200
    assert allowed.json()["total"] >= 1


@pytest.mark.asyncio
async def test_connector_config_response_is_credential_free(
    pg_session: AsyncSession,
    tenant_client: httpx.AsyncClient,
) -> None:
    secret = "connector-channel-secret"
    channel = await tenant_client.post(
        "/api/v1/tenant/channels",
        headers=_headers(),
        json={
            "channel_type": "zendesk",
            "routing_address": "https://tenant.zendesk.example",
            "credentials": {"api_key": secret},
            "webhook_secret": "connector-webhook-secret",
        },
    )
    assert channel.status_code == 200
    await _seed_connector(pg_session, tool_name="refund.redaction")

    response = await tenant_client.get(
        "/api/v1/tenant/connectors/refund.redaction",
        headers=_headers("tenant-acme", "reader"),
    )

    assert response.status_code == 200
    body = response.json()
    item = body["items"][0]
    assert set(item) == {
        "connector_type",
        "tool_name",
        "http_method",
        "endpoint_template",
        "endpoint_host",
        "field_mappings",
        "idempotency_header_name",
        "response_parse",
        "success_status_codes",
        "status",
        "version",
        "configured_by",
        "source_approval_id",
        "content_sha256",
        "previous_version_sha256",
        "created_at",
        "updated_at",
    }
    assert "credentials" not in item
    assert "credentials_enc" not in item
    assert "webhook_secret" not in item
    assert secret not in response.text
    assert "connector-webhook-secret" not in response.text


@pytest.mark.asyncio
async def test_knowledge_and_policy_endpoints_increment_versions(
    tenant_client: httpx.AsyncClient,
) -> None:
    doc = await tenant_client.post(
        "/api/v1/tenant/knowledge",
        headers=_headers(),
        json={
            "title": "Warranty FAQ",
            "content": "v1",
            "document_type": "faq",
        },
    )
    assert doc.status_code == 200
    document_id = doc.json()["document_id"]
    assert doc.json()["version"] == 1

    updated_doc = await tenant_client.put(
        f"/api/v1/tenant/knowledge/{document_id}",
        headers=_headers(),
        json={"content": "v2", "status": "active"},
    )
    assert updated_doc.status_code == 200
    assert updated_doc.json()["version"] == 2
    assert updated_doc.json()["content"] == "v2"

    policy = await tenant_client.post(
        "/api/v1/tenant/policies",
        headers=_headers(),
        json={
            "policy_type": "refund_limit",
            "parameters": {"max_refund_usd": 50, "currency": "USD"},
            "effective_from": "2026-05-22T00:00:00Z",
        },
    )
    assert policy.status_code == 200
    policy_id = policy.json()["policy_id"]
    assert policy.json()["version"] == 1

    updated_policy = await tenant_client.put(
        f"/api/v1/tenant/policies/{policy_id}",
        headers=_headers(),
        json={
            "parameters": {"max_refund_usd": 75, "currency": "USD"},
            "status": "active",
        },
    )
    assert updated_policy.status_code == 200
    assert updated_policy.json()["version"] == 2
    assert updated_policy.json()["parameters"]["max_refund_usd"] == 75


@pytest.mark.asyncio
async def test_tenant_lists_do_not_cross_tenant_boundary(
    tenant_client: httpx.AsyncClient,
) -> None:
    created = await tenant_client.post(
        "/api/v1/tenant/knowledge",
        headers=_headers("tenant-acme"),
        json={
            "title": "Escalation Matrix",
            "content": "acme only",
            "document_type": "escalation_matrix",
        },
    )
    assert created.status_code == 200

    own = await tenant_client.get(
        "/api/v1/tenant/knowledge",
        headers=_headers("tenant-acme"),
    )
    other = await tenant_client.get(
        "/api/v1/tenant/knowledge",
        headers=_headers("tenant-other"),
    )

    assert own.json()["total"] == 1
    assert other.json()["total"] == 0


@pytest.mark.asyncio
async def test_execution_governance_configuration_endpoint(
    tenant_client: httpx.AsyncClient,
) -> None:
    created = await tenant_client.post(
        "/api/v1/tenant/execution-governance",
        headers=_headers("tenant-acme"),
        json={
            "execution_quota": 10,
            "throughput_limit": 20,
            "throughput_window_minutes": 5,
            "governance_budget_limit": 30,
            "governance_budget_window_minutes": 15,
            "circuit_failure_threshold": 3,
            "circuit_window_minutes": 10,
            "circuit_cooldown_minutes": 2,
            "status": "active",
            "metadata": {"tier": "enterprise"},
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "active"
    assert body["execution_quota"] == 10
    assert body["metadata"] == {"tier": "enterprise"}

    listed = await tenant_client.get(
        "/api/v1/tenant/execution-governance",
        headers=_headers("tenant-acme"),
    )
    other = await tenant_client.get(
        "/api/v1/tenant/execution-governance",
        headers=_headers("tenant-other"),
    )
    breakers = await tenant_client.get(
        "/api/v1/tenant/execution-governance/circuit-breakers",
        headers=_headers("tenant-acme"),
    )

    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert other.status_code == 200
    assert other.json()["total"] == 0
    assert breakers.status_code == 200
    assert breakers.json()["total"] == 1
    assert breakers.json()["items"][0]["state"] == "closed"


async def _seed_connector(
    session: AsyncSession,
    *,
    tenant_id: str = "tenant-acme",
    connector_type: str = "zendesk",
    tool_name: str = "refund.request",
    version: int = 1,
    status: str = "active",
) -> None:
    now = datetime(2026, 6, 4, tzinfo=timezone.utc)
    await session.merge(TenantRow(tenant_id=tenant_id))
    session.add(
        ConnectorConfigRow(
            tenant_id=tenant_id,
            connector_type=connector_type,
            tool_name=tool_name,
            http_method="POST",
            endpoint_template=f"https://{tool_name}.example.com/refunds/{{order_id}}",
            endpoint_host=f"{tool_name}.example.com",
            field_mappings={"order_id": "payload.order_id"},
            idempotency_header_name="X-Idempotency-Key",
            response_parse={"provider_id": "refund.id"},
            success_status_codes=[200, 201, 202],
            status=status,
            version=version,
            configured_by="principal-config",
            source_approval_id=f"approval-{tool_name}-{version}",
            content_sha256="a" * 64,
            previous_version_sha256=None if version == 1 else "b" * 64,
            created_at=now,
            updated_at=now,
        )
    )
    await session.flush()
