"""PR-D7 tests for supervisor read endpoints."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.authority import require_tenant_supervisor_read
from app.dependencies.database import get_db_session
from app.dependencies.services import (
    get_supervisor_inbox_service,
    get_supervisor_repository,
)
from app.identity import AuthorityContext
from app.main import create_app
from app.supervisor.persistence import (
    EscalationDecisionRecord,
    EvaluationEvidenceRecord,
    InspectionRecord,
    PostgresSupervisorRepository,
    QAEvaluationRecord,
    RuntimeFindingRecord,
    SupervisorDecisionRecord,
)
from app.qa.persistence import PostgresQAPersistence
from app.services.supervisor_inbox_service import SupervisorInboxService
from app.trainer.persistence import PostgresTrainingRecommendationRepository
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]


@pytest.fixture
def pg_tenant_id() -> str:
    return "tenant-acme"


@pytest_asyncio.fixture
async def sup_client(
    pg_session: AsyncSession,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()

    async def _override() -> AsyncIterator[AsyncSession]:
        yield pg_session

    app.dependency_overrides[get_db_session] = _override
    async def _supervisor_authority() -> AuthorityContext:
        return AuthorityContext(
            tenant_id="tenant-acme",
            capabilities=("tenant.supervisor.read",),
        )

    async def _supervisor_repository() -> PostgresSupervisorRepository:
        return PostgresSupervisorRepository(pg_session)

    async def _supervisor_inbox_service() -> SupervisorInboxService:
        return SupervisorInboxService(
            supervisor_repository=PostgresSupervisorRepository(pg_session),
            qa_persistence=PostgresQAPersistence(pg_session),
            training_repository=PostgresTrainingRecommendationRepository(pg_session),
        )

    app.dependency_overrides[require_tenant_supervisor_read] = _supervisor_authority
    app.dependency_overrides[get_supervisor_repository] = _supervisor_repository
    app.dependency_overrides[get_supervisor_inbox_service] = _supervisor_inbox_service
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client


def _at(s: int = 0) -> str:
    return datetime(2026, 5, 19, 9, 0, s, tzinfo=timezone.utc).isoformat()


def _decision() -> SupervisorDecisionRecord:
    return SupervisorDecisionRecord(
        decision_id=str(uuid.uuid4()),
        kind="accept",
        aggregate_score=0.95,
        finding_ids=(),
        escalation_ids=(),
        reason="all passed",
        decided_at=_at(),
    )


def _inspection(*, tenant_id: str | None = "tenant-acme") -> InspectionRecord:
    return InspectionRecord(
        inspection_id=str(uuid.uuid4()),
        execution_id=str(uuid.uuid4()),
        runtime_instance_id=str(uuid.uuid4()),
        correlation_id=None,
        request_id=None,
        tenant_id=tenant_id,
        inspection_mode="synchronous",
        decision=_decision(),
        evaluator_names=("test_evaluator",),
        started_at=_at(),
        ended_at=_at(),
        latency_ms=1.0,
    )


def _finding(*, inspection_id: str) -> RuntimeFindingRecord:
    return RuntimeFindingRecord(
        finding_id=str(uuid.uuid4()),
        evaluator_name="test",
        category="quality",
        severity="low",
        code="x.y",
        message="hi",
        evidence=EvaluationEvidenceRecord(execution_id=str(uuid.uuid4())),
        detected_at=_at(),
        metadata={"inspection_id": inspection_id},
    )


def _evaluation(*, inspection_id: str) -> QAEvaluationRecord:
    return QAEvaluationRecord(
        inspection_id=inspection_id,
        evaluator_name="test_evaluator",
        status="passed",
        score=0.95,
        finding_ids=(),
        started_at=_at(),
        ended_at=_at(),
        latency_ms=0.5,
    )


def _escalation(*, inspection_id: str) -> EscalationDecisionRecord:
    return EscalationDecisionRecord(
        escalation_id=str(uuid.uuid4()),
        inspection_id=inspection_id,
        decision_id=str(uuid.uuid4()),
        level="human_review",
        reason="severity high",
        triggering_finding_ids=(),
        decided_at=_at(),
    )


async def _seed_inspection(
    pg_session: AsyncSession, record: InspectionRecord
) -> None:
    repo = PostgresSupervisorRepository(pg_session)
    await repo.record_inspection(record)


async def _seed_finding(
    pg_session: AsyncSession, record: RuntimeFindingRecord
) -> None:
    repo = PostgresSupervisorRepository(pg_session)
    await repo.record_finding(record)


async def _seed_evaluation(
    pg_session: AsyncSession, record: QAEvaluationRecord
) -> None:
    repo = PostgresSupervisorRepository(pg_session)
    await repo.record_evaluation(record)


async def _seed_escalation(
    pg_session: AsyncSession, record: EscalationDecisionRecord
) -> None:
    repo = PostgresSupervisorRepository(pg_session)
    await repo.record_escalation(record)


def _headers(tenant: str = "tenant-acme") -> dict[str, str]:
    return {"X-Tenant-ID": tenant, "X-Principal-ID": "principal-test"}


# ─── Inspection ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_inspection_returns_200(
    sup_client: httpx.AsyncClient, pg_session: AsyncSession
) -> None:
    record = _inspection(tenant_id="tenant-acme")
    await _seed_inspection(pg_session, record)
    response = await sup_client.get(
        f"/api/v1/supervisor/inspections/{record.inspection_id}",
        headers=_headers("tenant-acme"),
    )
    assert response.status_code == 200
    assert response.json()["inspection_id"] == record.inspection_id


@pytest.mark.asyncio
async def test_get_inspection_404_for_cross_tenant(
    sup_client: httpx.AsyncClient,
    pg_session: AsyncSession,
    pg_seed_session: AsyncSession,
) -> None:
    record = _inspection(tenant_id="tenant-other")
    await _seed_inspection(pg_seed_session, record)
    response = await sup_client.get(
        f"/api/v1/supervisor/inspections/{record.inspection_id}",
        headers=_headers("tenant-acme"),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_inspections_clamps_to_tenant(
    sup_client: httpx.AsyncClient,
    pg_session: AsyncSession,
    pg_seed_session: AsyncSession,
) -> None:
    await _seed_inspection(pg_session, _inspection(tenant_id="tenant-acme"))
    await _seed_inspection(pg_session, _inspection(tenant_id="tenant-acme"))
    await _seed_inspection(
        pg_seed_session, _inspection(tenant_id="tenant-other")
    )
    response = await sup_client.get(
        "/api/v1/supervisor/inspections",
        headers=_headers("tenant-acme"),
    )
    assert response.status_code == 200
    assert response.json()["total"] == 2


# ─── Sub-record reads inherit tenant scope ───────────────────────────────


@pytest.mark.asyncio
async def test_sub_records_inherit_tenant_scope(
    sup_client: httpx.AsyncClient, pg_session: AsyncSession
) -> None:
    record = _inspection(tenant_id="tenant-acme")
    await _seed_inspection(pg_session, record)
    await _seed_finding(
        pg_session, _finding(inspection_id=record.inspection_id)
    )
    await _seed_evaluation(
        pg_session, _evaluation(inspection_id=record.inspection_id)
    )
    await _seed_escalation(
        pg_session, _escalation(inspection_id=record.inspection_id)
    )

    # Owning tenant sees all three.
    for sub in ("findings", "evaluations", "escalations"):
        response = await sup_client.get(
            f"/api/v1/supervisor/inspections/{record.inspection_id}/{sub}",
            headers=_headers("tenant-acme"),
        )
        assert response.status_code == 200
        assert len(response.json()["items"]) == 1

    # Cross-tenant sees empty across all three.
    for sub in ("findings", "evaluations", "escalations"):
        response = await sup_client.get(
            f"/api/v1/supervisor/inspections/{record.inspection_id}/{sub}",
            headers=_headers("tenant-other"),
        )
        assert response.status_code == 200
        assert response.json()["items"] == []


@pytest.mark.asyncio
async def test_get_inspection_401_when_anonymous(
    sup_client: httpx.AsyncClient,
) -> None:
    response = await sup_client.get(
        f"/api/v1/supervisor/inspections/{uuid.uuid4()}",
    )
    assert response.status_code == 401
