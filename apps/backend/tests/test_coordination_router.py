"""PR-D4 tests for coordination read endpoints. Same pattern as
the governance router tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.coordination.persistence import (
    CoordinationRecord,
    PostgresCoordinationPersistence,
)
from app.dependencies.database import get_db_session
from app.main import create_app
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]


@pytest_asyncio.fixture
async def coord_client(
    pg_session: AsyncSession,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()

    async def _override() -> AsyncIterator[AsyncSession]:
        yield pg_session

    app.dependency_overrides[get_db_session] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client


def _at(s: int = 0) -> str:
    return datetime(2026, 5, 19, 9, 0, s, tzinfo=timezone.utc).isoformat()


def _build_envelope(
    *,
    coordination_id: str | None = None,
    tenant_id: str | None = "tenant-acme",
    sender_id: str = "agent-a",
    recipient_id: str = "agent-b",
    correlation_id: str | None = None,
) -> CoordinationRecord:
    return CoordinationRecord(
        coordination_id=coordination_id or str(uuid.uuid4()),
        message_id=str(uuid.uuid4()),
        sender_id=sender_id,
        recipient_id=recipient_id,
        recipient_kind="agent",
        direction="peer",
        message_type="task",
        priority=5,
        status="dispatched",
        sequence=0,
        runtime_instance_id=str(uuid.uuid4()),
        correlation_id=correlation_id,
        parent_coordination_id=None,
        parent_message_id=None,
        in_reply_to=None,
        request_id=None,
        tenant_id=tenant_id,
        governance_decision_id=None,
        governance_chain_id=None,
        payload_content_type="application/json",
        payload_schema_version="1",
        payload_body={"action": "noop"},
        created_at=_at(),
        dispatched_at=_at(),
    )


async def _seed(
    pg_session: AsyncSession, record: CoordinationRecord
) -> None:
    repo = PostgresCoordinationPersistence(pg_session)
    await repo.record_envelope(record)


def _headers(tenant: str = "tenant-acme") -> dict[str, str]:
    return {"X-Tenant-ID": tenant, "X-Principal-ID": "principal-test"}


# ─── Point read ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_envelope_returns_200_when_tenant_matches(
    coord_client: httpx.AsyncClient, pg_session: AsyncSession
) -> None:
    record = _build_envelope(tenant_id="tenant-acme")
    await _seed(pg_session, record)
    response = await coord_client.get(
        f"/api/v1/coordination/envelopes/{record.coordination_id}",
        headers=_headers("tenant-acme"),
    )
    assert response.status_code == 200
    assert response.json()["coordination_id"] == record.coordination_id


@pytest.mark.asyncio
async def test_get_envelope_returns_404_for_cross_tenant(
    coord_client: httpx.AsyncClient, pg_session: AsyncSession
) -> None:
    record = _build_envelope(tenant_id="tenant-other")
    await _seed(pg_session, record)
    response = await coord_client.get(
        f"/api/v1/coordination/envelopes/{record.coordination_id}",
        headers=_headers("tenant-acme"),
    )
    assert response.status_code == 404
    assert "envelope_not_found" in response.text


@pytest.mark.asyncio
async def test_get_envelope_returns_404_for_missing(
    coord_client: httpx.AsyncClient,
) -> None:
    response = await coord_client.get(
        f"/api/v1/coordination/envelopes/{uuid.uuid4()}",
        headers=_headers(),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_envelope_returns_401_when_anonymous(
    coord_client: httpx.AsyncClient,
) -> None:
    response = await coord_client.get(
        f"/api/v1/coordination/envelopes/{uuid.uuid4()}",
    )
    assert response.status_code == 401


# ─── List ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_envelopes_clamps_to_tenant(
    coord_client: httpx.AsyncClient, pg_session: AsyncSession
) -> None:
    await _seed(pg_session, _build_envelope(tenant_id="tenant-acme"))
    await _seed(pg_session, _build_envelope(tenant_id="tenant-acme"))
    await _seed(pg_session, _build_envelope(tenant_id="tenant-other"))
    response = await coord_client.get(
        "/api/v1/coordination/envelopes",
        headers=_headers("tenant-acme"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert all(item["tenant_id"] == "tenant-acme" for item in body["items"])


@pytest.mark.asyncio
async def test_list_envelopes_filters_by_correlation(
    coord_client: httpx.AsyncClient, pg_session: AsyncSession
) -> None:
    await _seed(
        pg_session,
        _build_envelope(tenant_id="tenant-acme", correlation_id="corr-1"),
    )
    await _seed(
        pg_session,
        _build_envelope(tenant_id="tenant-acme", correlation_id="corr-2"),
    )
    response = await coord_client.get(
        "/api/v1/coordination/envelopes",
        params={"correlation_id": "corr-1"},
        headers=_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["correlation_id"] == "corr-1"


@pytest.mark.asyncio
async def test_list_envelopes_pagination_clamped(
    coord_client: httpx.AsyncClient,
) -> None:
    response = await coord_client.get(
        "/api/v1/coordination/envelopes",
        params={"limit": 10000},
        headers=_headers(),
    )
    assert response.status_code == 422
