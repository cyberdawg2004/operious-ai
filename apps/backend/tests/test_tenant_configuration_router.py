"""Phase 2.5-A tenant configuration endpoint tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import VerifiedIdentity
from app.auth.providers import StaticTokenProvider
from app.core.config import get_settings
from app.dependencies.authority import TENANT_CONFIG_DOMAIN_WRITE_CAPABILITIES
from app.dependencies.database import get_db_session
from app.main import create_app
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
            "tenant-other-admin": VerifiedIdentity(
                tenant_id="tenant-other",
                principal_id="principal-a",
                capabilities=frozenset(TENANT_CONFIG_DOMAIN_WRITE_CAPABILITIES),
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


def _headers(tenant: str = "tenant-acme") -> dict[str, str]:
    return {"Authorization": f"Bearer {tenant}-admin"}


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
