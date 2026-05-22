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
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport


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


for _env_key in ("DATABASE_URL", "TEST_DATABASE_URL"):
    _load_dotenv_key(_env_key)

test_database_url = os.environ.get("TEST_DATABASE_URL", "")
if test_database_url.startswith("postgresql+asyncpg://"):
    os.environ["DATABASE_URL"] = test_database_url
elif not test_database_url:
    database_url = os.environ.get("DATABASE_URL", "")
    if database_url.startswith("postgresql+asyncpg://"):
        os.environ["TEST_DATABASE_URL"] = database_url


def _has_asyncpg_test_database_url() -> bool:
    return os.environ.get("TEST_DATABASE_URL", "").startswith(
        "postgresql+asyncpg://"
    )


requires_postgres = pytest.mark.skipif(
    not _has_asyncpg_test_database_url(),
    reason=(
        "requires TEST_DATABASE_URL with an asyncpg DSN, for example "
        "postgresql+asyncpg://test:test@localhost:5433/operious_test"
    ),
)


def _create_app():
    from app.main import create_app

    return create_app()


# Single authority source for all smoke tests.
# AUTH_ENABLED=False so no JWT needed.
# X-Tenant-ID alone satisfies the XOR authority rule.
SMOKE_HEADERS = {"X-Tenant-ID": "anker-pilot"}


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
        response = await client.post(
            "/api/v1/boundary/translation/ingress",
            json={
                "external_id": "smoke-001",
                "channel": "email",
                "raw_content": "My Anker cable stopped working",
                "language_code": "en"
            },
            headers=SMOKE_HEADERS
        )
        assert response.status_code == 200
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
        response = await client.post(
            "/api/v1/coordination/dispatch",
            json={"ingress_id": "smoke-001"},
            headers=SMOKE_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert "dispatch_id" in data
        assert "governance_decision_id" in data


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

        # Step 1 — ingest ticket
        ingress = await client.post(
            "/api/v1/boundary/translation/ingress",
            json={
                "external_id": "smoke-e2e-001",
                "channel": "email",
                "raw_content": "My Anker PowerCore stopped charging",
                "language_code": "en"
            },
            headers=SMOKE_HEADERS
        )
        assert ingress.status_code == 200
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
