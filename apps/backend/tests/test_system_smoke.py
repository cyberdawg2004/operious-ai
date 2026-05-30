"""
System smoke test.
Verifies the full operational chain end to end.

test_health_endpoint_live   → PASSES now
test_ticket_ingress_chain   → PASSES now
test_dispatch_governance    → PASSES now
test_full_chain             → PASSES now
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

from tests.conftest import (
    TEST_DATABASE_URL_ENV,
    database_url_skip_reason,
    requires_postgres,
)


pytestmark = pytest.mark.smoke


def _load_dotenv_key(key: str) -> None:
    """Load one simple KEY=VALUE entry from repo .env without logging it."""
    if os.environ.get(key):
        return
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() != key:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")
        return


for _env_key in (TEST_DATABASE_URL_ENV,):
    _load_dotenv_key(_env_key)


def _create_app():
    os.environ.setdefault(
        "TENANT_CREDENTIAL_MASTER_KEY",
        "system-smoke-master-key-material-32-bytes",
    )
    if database_url_skip_reason() is None:
        os.environ["DATABASE_URL"] = os.environ[TEST_DATABASE_URL_ENV]
    from app.core.config import get_settings
    from app.dependencies.authority import require_tenant_admin
    from app.identity.authority import AuthorityContext
    from app.identity.primitives import PrincipalId
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()

    # Tenant configuration writes now require the ``tenant_admin``
    # capability (S-02). Smoke tests authenticate with X-Tenant-ID
    # headers (no capabilities), so stand in an admin authority.
    def _admin_authority() -> AuthorityContext:
        return AuthorityContext(
            principal_id=PrincipalId("smoke-operator"),
            capabilities=frozenset({"tenant_admin"}),
        )

    app.dependency_overrides[require_tenant_admin] = _admin_authority
    return app


# Single authority source for all smoke tests.
# AUTH_ENABLED=False so no JWT needed.
# X-Tenant-ID alone satisfies the XOR authority rule.
SMOKE_HEADERS = {"X-Tenant-ID": "anker-pilot"}
SMOKE_ADMIN_HEADERS = {
    **SMOKE_HEADERS,
    "X-Principal-ID": "smoke-operator",
}


def _smoke_external_id(label: str) -> str:
    """Unique ticket id so repeated smoke runs do not replay old DB rows."""
    return f"{label}-{uuid.uuid4().hex}"


async def _ensure_execution_governance(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/tenant/execution-governance",
        json={
            "execution_quota": 100_000,
            "throughput_limit": 100_000,
            "throughput_window_minutes": 60,
            "governance_budget_limit": 100_000,
            "governance_budget_window_minutes": 60,
            "circuit_failure_threshold": 100_000,
            "circuit_window_minutes": 60,
            "circuit_cooldown_minutes": 1,
            "status": "active",
            "metadata": {"origin": "system_smoke"},
        },
        headers=SMOKE_ADMIN_HEADERS,
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_endpoint_live():
    """
    Baseline: system boots and health endpoint responds.
    MUST PASS before any other work begins.
    """
    app = _create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data


@pytest.mark.asyncio
@requires_postgres
async def test_ticket_ingress_chain():
    """
    FAILS with 404 until PR-W1 is complete.
    Success condition: 200 with ingress_id in response.
    """
    app = _create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test"
    ) as client:
        external_id = _smoke_external_id("smoke-ingress")
        response = await client.post(
            "/api/v1/boundary/translation/ingress",
            json={
                "external_id": external_id,
                "channel": "email",
                "raw_content": "My Anker cable stopped working",
                "language_code": "en"
            },
            headers=SMOKE_HEADERS
        )
        assert response.status_code == 202
        data = response.json()
        assert "ingress_id" in data
        assert "canonical_envelope_id" in data


@pytest.mark.asyncio
@requires_postgres
async def test_dispatch_governance_chain():
    """
    Live dispatch path returns a dispatch id and governance decision id.
    """
    app = _create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test"
    ) as client:
        await _ensure_execution_governance(client)
        external_id = _smoke_external_id("smoke-dispatch")
        ingress = await client.post(
            "/api/v1/boundary/translation/ingress",
            json={
                "external_id": external_id,
                "channel": "email",
                "raw_content": "My Anker cable stopped working",
                "language_code": "en"
            },
            headers=SMOKE_HEADERS
        )
        assert ingress.status_code == 202
        ingress_id = ingress.json()["ingress_id"]

        response = await client.post(
            "/api/v1/coordination/dispatch",
            json={"ingress_id": ingress_id},
            headers=SMOKE_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert "dispatch_id" in data
        assert "governance_decision_id" in data
        assert data["session_id"] is not None
        assert data["halted"] is False


@pytest.mark.asyncio
@requires_postgres
async def test_full_ticket_to_timeline_chain():
    """
    Full ticket path reaches dispatch, session timeline, and governance.
    """
    app = _create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test"
    ) as client:
        await _ensure_execution_governance(client)
        external_id = _smoke_external_id("smoke-e2e")

        # Step 1 — ingest ticket
        ingress = await client.post(
            "/api/v1/boundary/translation/ingress",
            json={
                "external_id": external_id,
                "channel": "email",
                "raw_content": "My Anker PowerCore stopped charging",
                "language_code": "en"
            },
            headers=SMOKE_HEADERS
        )
        assert ingress.status_code == 202
        ingress_id = ingress.json()["ingress_id"]

        # Step 2 — dispatch through governance
        dispatch = await client.post(
            "/api/v1/coordination/dispatch",
            json={"ingress_id": ingress_id},
            headers=SMOKE_HEADERS
        )
        assert dispatch.status_code == 200
        session_id = dispatch.json()["session_id"]

        # Step 3 — verify session timeline populated
        timeline = await client.get(
            f"/api/v1/session/{session_id}/timeline",
            headers=SMOKE_HEADERS
        )
        assert timeline.status_code == 200
        events = timeline.json()["events"]
        assert len(events) > 0

        # Step 4 — verify governance decision recorded
        governance = await client.get(
            "/api/v1/governance/decisions",
            headers=SMOKE_HEADERS
        )
        assert governance.status_code == 200
        assert len(governance.json()["decisions"]) > 0
