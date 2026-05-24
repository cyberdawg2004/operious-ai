"""PR-D8 tests for session read endpoints."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.database import get_db_session
from app.main import create_app
from app.session.enums import (
    SessionContinuityMode,
    SessionCorrelationKind,
    SessionEventKind,
    SessionLifecyclePhase,
    SessionScope,
)
from app.session.identity import (
    SessionCorrelationId,
    SessionEventId,
    SessionId,
    SessionLineageId,
)
from app.session.persistence import (
    PostgresSessionPersistence,
    SessionCorrelationRecord,
    SessionEventRecord,
    SessionRecord,
)
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]


@pytest.fixture
def pg_tenant_id() -> str:
    return "tenant-acme"


@pytest_asyncio.fixture
async def session_client(
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


def _at(s: int = 0) -> datetime:
    return datetime(2026, 5, 19, 9, 0, s, tzinfo=timezone.utc)


def _build_session(
    *,
    session_id: SessionId | None = None,
    tenant_id: str | None = "tenant-acme",
) -> SessionRecord:
    sid = session_id or SessionId(uuid.uuid4())
    lineage = SessionLineageId(uuid.uuid4())
    return SessionRecord(
        session_id=sid,
        scope=SessionScope.TENANT,
        external_handle="ext-handle",
        tenant_id=tenant_id,
        principal_id="principal-test",
        opened_at=_at(),
        lifecycle_phase=SessionLifecyclePhase.ACTIVE,
        lifecycle_recorded_at=_at(),
        lifecycle_reason=None,
        lineage_id=lineage,
        root_session_id=sid,
        parent_session_id=None,
        ancestor_session_ids=(),
        lineage_depth=0,
        sequence_head=0,
        revision=1,
    )


def _build_event(
    *,
    session_id: SessionId,
    sequence: int = 1,
    event_id: SessionEventId | None = None,
) -> SessionEventRecord:
    return SessionEventRecord(
        event_id=event_id or SessionEventId(uuid.uuid4()),
        session_id=session_id,
        sequence=sequence,
        kind=SessionEventKind.OPERATIONAL_OBSERVATION,
        continuity_mode=SessionContinuityMode.SYNCHRONOUS,
        occurred_at=_at(sequence),
        recorded_at=_at(sequence),
        payload={"text": "hi"},
    )


def _build_correlation(
    *,
    session_id: SessionId,
    correlation_id: SessionCorrelationId | None = None,
) -> SessionCorrelationRecord:
    return SessionCorrelationRecord(
        correlation_id=correlation_id or SessionCorrelationId(uuid.uuid4()),
        session_id=session_id,
        kind=SessionCorrelationKind.EXTERNAL,
        external_id="T123.456",
        recorded_at=_at(),
    )


async def _seed_session(
    pg_session: AsyncSession, record: SessionRecord
) -> None:
    repo = PostgresSessionPersistence(pg_session)
    await repo.save_session(record)


async def _seed_event(
    pg_session: AsyncSession, record: SessionEventRecord
) -> None:
    repo = PostgresSessionPersistence(pg_session)
    await repo.save_event(record)


async def _seed_correlation(
    pg_session: AsyncSession, record: SessionCorrelationRecord
) -> None:
    repo = PostgresSessionPersistence(pg_session)
    await repo.save_correlation(record)


def _headers(tenant: str = "tenant-acme") -> dict[str, str]:
    return {"X-Tenant-ID": tenant, "X-Principal-ID": "principal-test"}


# ─── Sessions ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_session_returns_200(
    session_client: httpx.AsyncClient, pg_session: AsyncSession
) -> None:
    record = _build_session(tenant_id="tenant-acme")
    await _seed_session(pg_session, record)
    response = await session_client.get(
        f"/api/v1/session/sessions/{record.session_id}",
        headers=_headers("tenant-acme"),
    )
    assert response.status_code == 200
    assert response.json()["session_id"] == str(record.session_id)


@pytest.mark.asyncio
async def test_get_session_404_for_cross_tenant(
    session_client: httpx.AsyncClient, pg_session: AsyncSession
) -> None:
    record = _build_session(tenant_id="tenant-other")
    await _seed_session(pg_session, record)
    response = await session_client.get(
        f"/api/v1/session/sessions/{record.session_id}",
        headers=_headers("tenant-acme"),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_session_404_for_malformed_uuid(
    session_client: httpx.AsyncClient,
) -> None:
    response = await session_client.get(
        "/api/v1/session/sessions/not-a-uuid",
        headers=_headers(),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_sessions_clamps_to_tenant(
    session_client: httpx.AsyncClient, pg_session: AsyncSession
) -> None:
    await _seed_session(pg_session, _build_session(tenant_id="tenant-acme"))
    await _seed_session(pg_session, _build_session(tenant_id="tenant-other"))
    response = await session_client.get(
        "/api/v1/session/sessions",
        headers=_headers("tenant-acme"),
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1


# ─── Events ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_events_for_session_inherits_tenant(
    session_client: httpx.AsyncClient, pg_session: AsyncSession
) -> None:
    session = _build_session(tenant_id="tenant-acme")
    await _seed_session(pg_session, session)
    # First event of a session MUST have sequence=0 (substrate
    # invariant from PR-B7: append-only timelines start at zero).
    await _seed_event(
        pg_session, _build_event(session_id=session.session_id, sequence=0)
    )
    await _seed_event(
        pg_session, _build_event(session_id=session.session_id, sequence=1)
    )

    # Owning tenant sees both events in sequence order.
    response = await session_client.get(
        f"/api/v1/session/sessions/{session.session_id}/events",
        headers=_headers("tenant-acme"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    sequences = [item["sequence"] for item in body["items"]]
    assert sequences == [0, 1]

    # Cross-tenant sees an empty page (parent invisible).
    response = await session_client.get(
        f"/api/v1/session/sessions/{session.session_id}/events",
        headers=_headers("tenant-other"),
    )
    assert response.status_code == 200
    assert response.json()["total"] == 0


@pytest.mark.asyncio
async def test_get_event_inherits_tenant_scope(
    session_client: httpx.AsyncClient, pg_session: AsyncSession
) -> None:
    session = _build_session(tenant_id="tenant-acme")
    await _seed_session(pg_session, session)
    event = _build_event(session_id=session.session_id, sequence=0)
    await _seed_event(pg_session, event)

    response = await session_client.get(
        f"/api/v1/session/events/{event.event_id}",
        headers=_headers("tenant-acme"),
    )
    assert response.status_code == 200

    response = await session_client.get(
        f"/api/v1/session/events/{event.event_id}",
        headers=_headers("tenant-other"),
    )
    assert response.status_code == 404


# ─── Correlations ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_correlation_endpoints_inherit_tenant_scope(
    session_client: httpx.AsyncClient, pg_session: AsyncSession
) -> None:
    session = _build_session(tenant_id="tenant-acme")
    await _seed_session(pg_session, session)
    correlation = _build_correlation(session_id=session.session_id)
    await _seed_correlation(pg_session, correlation)

    response = await session_client.get(
        f"/api/v1/session/correlations/{correlation.correlation_id}",
        headers=_headers("tenant-acme"),
    )
    assert response.status_code == 200

    response = await session_client.get(
        f"/api/v1/session/correlations/{correlation.correlation_id}",
        headers=_headers("tenant-other"),
    )
    assert response.status_code == 404

    response = await session_client.get(
        f"/api/v1/session/sessions/{session.session_id}/correlations",
        headers=_headers("tenant-acme"),
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1


@pytest.mark.asyncio
async def test_session_router_returns_401_when_anonymous(
    session_client: httpx.AsyncClient,
) -> None:
    response = await session_client.get(
        f"/api/v1/session/sessions/{uuid.uuid4()}",
    )
    assert response.status_code == 401
