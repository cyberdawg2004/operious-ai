"""PR-D3 tests for governance read endpoints.

End-to-end against the real Postgres backend through the
``pg_session`` fixture. Every test is async and uses
``httpx.AsyncClient`` over an in-process ``ASGITransport`` so the
test, the FastAPI app, the dependency overrides, and the seeded
records all share the SAME asyncio event loop. Mixing
``TestClient`` (sync, runs the app on a separate thread/loop)
with the pytest-asyncio ``pg_session`` fixture deadlocks because
the asyncpg connection bound to one loop cannot be awaited from
another.

Authentication is via the legacy ``X-Tenant-ID`` / ``X-Principal-ID``
headers (the ``authority_source = "header"`` middleware path) —
no auth provider is configured in the test app, so no JWKS
round-trip is needed.

Pinned contract:

* 200 with full record shape on valid tenant-scoped reads.
* 404 (NOT 403) when the row exists for another tenant — the
  HTTP layer mirrors the repository's invisibility-equals-absence
  contract from PR-B2.
* 404 on genuine not-found.
* 401 ``authority_required`` on anonymous requests.
* 400 ``tenant_axis_missing`` when the principal has no tenant.
* Query-endpoint pagination clamps ``limit`` to a server bound;
  caller-supplied ``tenant_id`` is silently ignored (router
  forces scope from request authority).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.database import get_db_session
from app.governance.persistence import (
    GovernanceDecisionRecord,
    GovernanceTraceRecord,
    PostgresGovernanceRepository,
)
from app.main import create_app
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]


# ─── Fixtures ────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def governance_client(
    pg_session: AsyncSession,
) -> AsyncIterator[httpx.AsyncClient]:
    """``httpx.AsyncClient`` over an in-process ASGITransport with
    the request-scoped DB session overridden to yield the test's
    ``pg_session`` fixture.

    Single-loop semantics: TestClient cannot be used here because
    it runs the ASGI app on a separate thread with its own event
    loop — pg_session's asyncpg connection is bound to the
    pytest-asyncio loop and would deadlock under TestClient's
    cross-loop access. ASGITransport runs everything in the
    caller's loop.
    """
    app = create_app()

    async def _override_db_session() -> AsyncIterator[AsyncSession]:
        yield pg_session

    app.dependency_overrides[get_db_session] = _override_db_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client


def _at(s: int = 0) -> str:
    return datetime(2026, 5, 19, 9, 0, s, tzinfo=timezone.utc).isoformat()


def _build_decision(
    *,
    decision_id: str | None = None,
    tenant_id: str | None = "tenant-acme",
    stage: str = "pre_request",
    final_decision: str = "allow",
    correlation_id: str | None = None,
    request_id: str | None = None,
) -> GovernanceDecisionRecord:
    return GovernanceDecisionRecord(
        decision_id=decision_id or str(uuid.uuid4()),
        decision=final_decision,
        stage=stage,
        policy_chain_id="test.chain",
        reason="test",
        decided_at=_at(),
        correlation_id=correlation_id,
        request_id=request_id,
        tenant_id=tenant_id,
    )


def _build_trace(
    *,
    decision_id: str,
    tenant_id: str | None = "tenant-acme",
) -> GovernanceTraceRecord:
    return GovernanceTraceRecord(
        decision_id=decision_id,
        request_id=None,
        correlation_id=None,
        stage="pre_request",
        action="check",
        resource="thing",
        actor="agent:test",
        tenant_id=tenant_id,
        subject_kind="generic",
        started_at=_at(),
        ended_at=_at(),
        latency_ms=0.5,
        status="ok",
        final_decision="allow",
        policy_chain_id="test.chain",
        rule_count=0,
        violation_count=0,
        restriction_count=0,
        enforcement_handler=None,
        enforcement_status=None,
        enforcement_latency_ms=None,
    )


async def _seed_decision(
    pg_session: AsyncSession, record: GovernanceDecisionRecord
) -> None:
    """Insert a governance decision via the production repository
    bound to the test session. Awaited in the same loop as the
    request, so the savepoint pattern in PR-B8 holds correctly."""
    repo = PostgresGovernanceRepository(pg_session)
    await repo.record_decision(record)


async def _seed_trace(
    pg_session: AsyncSession, record: GovernanceTraceRecord
) -> None:
    repo = PostgresGovernanceRepository(pg_session)
    await repo.record_trace(record)


def _tenant_headers(
    *, tenant: str = "tenant-acme", principal: str = "principal-test"
) -> dict[str, str]:
    return {
        "X-Tenant-ID": tenant,
        "X-Principal-ID": principal,
    }


# ─── GET /decisions/{id} ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_decision_returns_200_when_tenant_matches(
    governance_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    record = _build_decision(tenant_id="tenant-acme")
    await _seed_decision(pg_session, record)

    response = await governance_client.get(
        f"/api/v1/governance/decisions/{record.decision_id}",
        headers=_tenant_headers(tenant="tenant-acme"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision_id"] == record.decision_id
    assert body["tenant_id"] == "tenant-acme"
    assert body["decision"] == "allow"


@pytest.mark.asyncio
async def test_get_decision_returns_404_for_cross_tenant_row(
    governance_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    """Cross-tenant access returns 404, NOT 403 — invisibility is
    indistinguishable from absence to prevent existence
    enumeration across tenants."""
    record = _build_decision(tenant_id="tenant-other")
    await _seed_decision(pg_session, record)

    response = await governance_client.get(
        f"/api/v1/governance/decisions/{record.decision_id}",
        headers=_tenant_headers(tenant="tenant-acme"),
    )
    assert response.status_code == 404
    assert "decision_not_found" in response.text


@pytest.mark.asyncio
async def test_get_decision_returns_404_for_missing_id(
    governance_client: httpx.AsyncClient,
) -> None:
    response = await governance_client.get(
        f"/api/v1/governance/decisions/{uuid.uuid4()}",
        headers=_tenant_headers(),
    )
    assert response.status_code == 404
    assert "decision_not_found" in response.text


@pytest.mark.asyncio
async def test_get_decision_returns_401_when_anonymous(
    governance_client: httpx.AsyncClient,
) -> None:
    response = await governance_client.get(
        f"/api/v1/governance/decisions/{uuid.uuid4()}",
    )
    assert response.status_code == 401
    assert "authority_required" in response.text


@pytest.mark.asyncio
async def test_get_decision_returns_400_when_tenant_axis_missing(
    governance_client: httpx.AsyncClient,
) -> None:
    """Authenticated principal without a tenant axis → 400
    ``tenant_axis_missing``. The platform refuses to enumerate
    tenant-scoped resources under a tenant-less authority."""
    response = await governance_client.get(
        f"/api/v1/governance/decisions/{uuid.uuid4()}",
        headers={"X-Principal-ID": "principal-test"},
    )
    assert response.status_code == 400
    assert "tenant_axis_missing" in response.text


# ─── GET /decisions (list) ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_decisions_clamps_to_authenticated_tenant(
    governance_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    await _seed_decision(pg_session, _build_decision(tenant_id="tenant-acme"))
    await _seed_decision(pg_session, _build_decision(tenant_id="tenant-acme"))
    await _seed_decision(pg_session, _build_decision(tenant_id="tenant-other"))

    response = await governance_client.get(
        "/api/v1/governance/decisions",
        headers=_tenant_headers(tenant="tenant-acme"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert all(item["tenant_id"] == "tenant-acme" for item in body["items"])


@pytest.mark.asyncio
async def test_list_decisions_ignores_caller_supplied_tenant_query_param(
    governance_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    """A request that supplies ``?tenant_id=tenant-other`` must NOT
    widen the scope. The router does not expose ``tenant_id`` as a
    query parameter — FastAPI ignores unknown extras and the
    response items are scoped to the authenticated tenant."""
    await _seed_decision(pg_session, _build_decision(tenant_id="tenant-other"))

    response = await governance_client.get(
        "/api/v1/governance/decisions",
        params={"tenant_id": "tenant-other"},
        headers=_tenant_headers(tenant="tenant-acme"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0  # tenant-acme has no rows; query was ignored


@pytest.mark.asyncio
async def test_list_decisions_pagination_limit_is_server_bounded(
    governance_client: httpx.AsyncClient,
) -> None:
    """``limit`` is bounded server-side (1..200). A request asking
    for ``limit=10000`` returns 422 (FastAPI validation) — the
    invariant is that the server NEVER honours an unbounded page
    size."""
    response = await governance_client.get(
        "/api/v1/governance/decisions",
        params={"limit": 10000},
        headers=_tenant_headers(),
    )
    assert response.status_code == 422


# ─── GET /traces/{id} ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_trace_returns_200_when_tenant_matches(
    governance_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    """Trace records reference the apex decision via FK (RESTRICT
    on delete). The seed sequence is therefore "decision first,
    then trace" — matches the production substrate's emission
    order."""
    decision_id = str(uuid.uuid4())
    await _seed_decision(
        pg_session,
        _build_decision(decision_id=decision_id, tenant_id="tenant-acme"),
    )
    await _seed_trace(
        pg_session,
        _build_trace(decision_id=decision_id, tenant_id="tenant-acme"),
    )

    response = await governance_client.get(
        f"/api/v1/governance/traces/{decision_id}",
        headers=_tenant_headers(tenant="tenant-acme"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision_id"] == decision_id
    assert body["tenant_id"] == "tenant-acme"


@pytest.mark.asyncio
async def test_get_trace_returns_404_for_cross_tenant(
    governance_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    decision_id = str(uuid.uuid4())
    await _seed_decision(
        pg_session,
        _build_decision(decision_id=decision_id, tenant_id="tenant-other"),
    )
    await _seed_trace(
        pg_session,
        _build_trace(decision_id=decision_id, tenant_id="tenant-other"),
    )

    response = await governance_client.get(
        f"/api/v1/governance/traces/{decision_id}",
        headers=_tenant_headers(tenant="tenant-acme"),
    )
    assert response.status_code == 404
    assert "trace_not_found" in response.text
