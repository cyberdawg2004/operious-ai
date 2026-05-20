"""
System smoke test.
Verifies the full operational chain end to end.

test_health_endpoint_live   → PASSES now
test_ticket_ingress_chain   → FAILS with 404 until PR-W1
test_dispatch_governance    → FAILS with 404 until PR-W2
test_full_chain             → FAILS with 404 until agents done

404 = route not built yet (expected and correct)
400 = authority conflict (bug — now fixed)
"""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import create_app


pytestmark = pytest.mark.smoke


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
    app = create_app()
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
@pytest.mark.requires_postgres
async def test_ticket_ingress_chain():
    """
    FAILS with 404 until PR-W1 is complete.
    Success condition: 200 with ingress_id in response.
    """
    app = create_app()
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
@pytest.mark.requires_postgres
async def test_dispatch_governance_chain():
    """
    FAILS with 404 until PR-W2 is complete.
    Success condition: 200 with dispatch_id
    and governance_decision_id in response.
    """
    app = create_app()
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
@pytest.mark.requires_postgres
async def test_full_ticket_to_timeline_chain():
    """
    FAILS with 404 until all agents are complete.
    The ultimate smoke test — full operational chain.
    When this passes the system is operationally verified.
    """
    app = create_app()
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