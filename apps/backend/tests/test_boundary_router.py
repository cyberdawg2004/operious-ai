"""PR-D6 tests for boundary read endpoints."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.boundary.enums import (
    BoundaryDirection,
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.identity import BoundaryEgressId, BoundaryIngressId
from app.boundary.persistence import (
    BoundaryEgressRecord,
    BoundaryIngressRecord,
    PostgresBoundaryPersistence,
)
from app.dependencies.database import get_db_session
from app.main import create_app
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]


@pytest.fixture
def pg_tenant_id() -> str:
    return "tenant-acme"


@pytest_asyncio.fixture
async def bnd_client(
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


def _build_ingress(
    *, tenant_id: str | None = "tenant-acme"
) -> BoundaryIngressRecord:
    return BoundaryIngressRecord(
        ingress_id=BoundaryIngressId(uuid.uuid4()),
        direction=BoundaryDirection.INGRESS,
        runtime_instance_id=uuid.uuid4(),
        sequence=0,
        source_type=BoundarySourceType.GENERIC,
        source_id="adapter-a",
        tenant_id=tenant_id,
        adapter_name="test",
        normalization_status=BoundaryNormalizationStatus.OK,
        message_type=BoundaryMessageType.MESSAGE_RECEIVED,
        replay_disposition=BoundaryReplayDisposition.NEW,
        replay_key=None,
        event_id=None,
        original_event_id=None,
        external_message_id="ext-1",
        external_conversation_id=None,
        external_emitted_at=None,
        received_at=_at(),
        started_at=_at(),
        ended_at=_at(),
        latency_ms=0.5,
        correlation_id=None,
        request_id=None,
        canonical_payload={"text": "hi"},
        error=None,
    )


def _build_egress(
    *, tenant_id: str | None = "tenant-acme"
) -> BoundaryEgressRecord:
    return BoundaryEgressRecord(
        egress_id=BoundaryEgressId(uuid.uuid4()),
        direction=BoundaryDirection.EGRESS,
        runtime_instance_id=uuid.uuid4(),
        sequence=0,
        source_type=BoundarySourceType.GENERIC,
        source_id="adapter-a",
        tenant_id=tenant_id,
        adapter_name="test",
        payload_body={"reply": "ack"},
        payload_content_type="application/json",
        payload_target_uri=None,
        payload_method=None,
        payload_headers={},
        translated_at=_at(),
        started_at=_at(),
        ended_at=_at(),
        latency_ms=0.5,
        correlation_id=None,
        request_id=None,
        error=None,
    )


async def _seed_ingress(
    pg_session: AsyncSession, record: BoundaryIngressRecord
) -> None:
    repo = PostgresBoundaryPersistence(pg_session)
    await repo.save_ingress(record)


async def _seed_egress(
    pg_session: AsyncSession, record: BoundaryEgressRecord
) -> None:
    repo = PostgresBoundaryPersistence(pg_session)
    await repo.save_egress(record)


def _headers(tenant: str = "tenant-acme") -> dict[str, str]:
    return {"X-Tenant-ID": tenant, "X-Principal-ID": "principal-test"}


# ─── Point reads ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_ingress_returns_200(
    bnd_client: httpx.AsyncClient, pg_session: AsyncSession
) -> None:
    record = _build_ingress(tenant_id="tenant-acme")
    await _seed_ingress(pg_session, record)
    response = await bnd_client.get(
        f"/api/v1/boundary/ingress/{record.ingress_id}",
        headers=_headers("tenant-acme"),
    )
    assert response.status_code == 200
    assert response.json()["ingress_id"] == str(record.ingress_id)


@pytest.mark.asyncio
async def test_get_ingress_returns_404_for_cross_tenant(
    bnd_client: httpx.AsyncClient, pg_session: AsyncSession
) -> None:
    record = _build_ingress(tenant_id="tenant-other")
    await _seed_ingress(pg_session, record)
    response = await bnd_client.get(
        f"/api/v1/boundary/ingress/{record.ingress_id}",
        headers=_headers("tenant-acme"),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_egress_returns_200(
    bnd_client: httpx.AsyncClient, pg_session: AsyncSession
) -> None:
    record = _build_egress(tenant_id="tenant-acme")
    await _seed_egress(pg_session, record)
    response = await bnd_client.get(
        f"/api/v1/boundary/egress/{record.egress_id}",
        headers=_headers("tenant-acme"),
    )
    assert response.status_code == 200
    assert response.json()["egress_id"] == str(record.egress_id)


@pytest.mark.asyncio
async def test_get_ingress_returns_404_for_malformed_uuid(
    bnd_client: httpx.AsyncClient,
) -> None:
    response = await bnd_client.get(
        "/api/v1/boundary/ingress/not-a-uuid",
        headers=_headers(),
    )
    assert response.status_code == 404


# ─── List ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_ingress_clamps_to_tenant(
    bnd_client: httpx.AsyncClient, pg_session: AsyncSession
) -> None:
    await _seed_ingress(pg_session, _build_ingress(tenant_id="tenant-acme"))
    await _seed_ingress(pg_session, _build_ingress(tenant_id="tenant-other"))
    response = await bnd_client.get(
        "/api/v1/boundary/ingress",
        headers=_headers("tenant-acme"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1


@pytest.mark.asyncio
async def test_list_egress_clamps_to_tenant(
    bnd_client: httpx.AsyncClient, pg_session: AsyncSession
) -> None:
    await _seed_egress(pg_session, _build_egress(tenant_id="tenant-acme"))
    await _seed_egress(pg_session, _build_egress(tenant_id="tenant-other"))
    response = await bnd_client.get(
        "/api/v1/boundary/egress",
        headers=_headers("tenant-acme"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1


@pytest.mark.asyncio
async def test_list_ingress_rejects_unknown_source_type(
    bnd_client: httpx.AsyncClient,
) -> None:
    response = await bnd_client.get(
        "/api/v1/boundary/ingress",
        params={"source_type": "not_a_real_source"},
        headers=_headers(),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_ingress_returns_401_when_anonymous(
    bnd_client: httpx.AsyncClient,
) -> None:
    response = await bnd_client.get(
        f"/api/v1/boundary/ingress/{uuid.uuid4()}",
    )
    assert response.status_code == 401
