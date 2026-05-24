"""PR-D5 tests for arbitration read endpoints."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.arbitration.enums import (
    ArbitrationAuthorityLevel,
    ArbitrationOutcome,
)
from app.arbitration.identity import (
    ArbitrationCaseId,
    ArbitrationChainId,
    ArbitrationEvaluationId,
)
from app.arbitration.persistence import (
    ArbitrationRecord,
    PostgresArbitrationPersistence,
)
from app.dependencies.database import get_db_session
from app.main import create_app
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]


@pytest.fixture
def pg_tenant_id() -> str:
    return "tenant-acme"


@pytest_asyncio.fixture
async def arb_client(
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


def _build_record(
    *,
    tenant_id: str | None = "tenant-acme",
    outcome: ArbitrationOutcome = ArbitrationOutcome.ARBITRATION_RESOLVED,
) -> ArbitrationRecord:
    eid = ArbitrationEvaluationId(uuid.uuid4())
    return ArbitrationRecord(
        evaluation_id=eid,
        chain_id=ArbitrationChainId(uuid.uuid4()),
        case_id=ArbitrationCaseId(uuid.uuid4()),
        runtime_instance_id=uuid.uuid4(),
        sequence=0,
        outcome=outcome,
        prevailing_authority_level=ArbitrationAuthorityLevel.GOVERNANCE,
        prevailing_authority_source_substrate="governance",
        prevailing_authority_source_id="signal-1",
        prevailing_authority_verdict="allow",
        reason="resolved",
        evaluator_names=("authority_precedence",),
        findings=(),
        conflicts=(),
        deadlock_witnesses=(),
        signal_count=1,
        recommendation_count=0,
        iteration_count=1,
        max_iterations=5,
        correlation_id=None,
        request_id=None,
        tenant_id=tenant_id,
        started_at=_at(),
        ended_at=_at(),
        latency_ms=0.5,
        error=None,
    )


async def _seed(
    pg_session: AsyncSession, record: ArbitrationRecord
) -> None:
    repo = PostgresArbitrationPersistence(pg_session)
    await repo.save(record)


def _headers(tenant: str = "tenant-acme") -> dict[str, str]:
    return {"X-Tenant-ID": tenant, "X-Principal-ID": "principal-test"}


# ─── Point read ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_evaluation_returns_200_when_tenant_matches(
    arb_client: httpx.AsyncClient, pg_session: AsyncSession
) -> None:
    record = _build_record(tenant_id="tenant-acme")
    await _seed(pg_session, record)
    response = await arb_client.get(
        f"/api/v1/arbitration/evaluations/{record.evaluation_id}",
        headers=_headers("tenant-acme"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["evaluation_id"] == str(record.evaluation_id)
    assert body["tenant_id"] == "tenant-acme"


@pytest.mark.asyncio
async def test_get_evaluation_returns_404_for_cross_tenant(
    arb_client: httpx.AsyncClient,
    pg_session: AsyncSession,
    pg_seed_session: AsyncSession,
) -> None:
    record = _build_record(tenant_id="tenant-other")
    await _seed(pg_seed_session, record)
    response = await arb_client.get(
        f"/api/v1/arbitration/evaluations/{record.evaluation_id}",
        headers=_headers("tenant-acme"),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_evaluation_returns_404_for_malformed_uuid(
    arb_client: httpx.AsyncClient,
) -> None:
    """Malformed UUID in the path → 404 (not 400) so the substrate
    refuses to leak whether the malformed id "would have matched"."""
    response = await arb_client.get(
        "/api/v1/arbitration/evaluations/not-a-uuid",
        headers=_headers(),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_evaluation_returns_401_when_anonymous(
    arb_client: httpx.AsyncClient,
) -> None:
    response = await arb_client.get(
        f"/api/v1/arbitration/evaluations/{uuid.uuid4()}",
    )
    assert response.status_code == 401


# ─── List ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_evaluations_clamps_to_tenant(
    arb_client: httpx.AsyncClient,
    pg_session: AsyncSession,
    pg_seed_session: AsyncSession,
) -> None:
    await _seed(pg_session, _build_record(tenant_id="tenant-acme"))
    await _seed(pg_session, _build_record(tenant_id="tenant-acme"))
    await _seed(pg_seed_session, _build_record(tenant_id="tenant-other"))
    response = await arb_client.get(
        "/api/v1/arbitration/evaluations",
        headers=_headers("tenant-acme"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2


@pytest.mark.asyncio
async def test_list_evaluations_filters_by_outcome(
    arb_client: httpx.AsyncClient, pg_session: AsyncSession
) -> None:
    await _seed(
        pg_session,
        _build_record(outcome=ArbitrationOutcome.ARBITRATION_RESOLVED),
    )
    await _seed(
        pg_session,
        _build_record(outcome=ArbitrationOutcome.ARBITRATION_CONFLICT),
    )
    response = await arb_client.get(
        "/api/v1/arbitration/evaluations",
        params={"outcome": "arbitration_conflict"},
        headers=_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["outcome"] == "arbitration_conflict"


@pytest.mark.asyncio
async def test_list_evaluations_rejects_unknown_outcome(
    arb_client: httpx.AsyncClient,
) -> None:
    response = await arb_client.get(
        "/api/v1/arbitration/evaluations",
        params={"outcome": "not_a_real_outcome"},
        headers=_headers(),
    )
    assert response.status_code == 422
    assert "invalid_outcome" in response.text
