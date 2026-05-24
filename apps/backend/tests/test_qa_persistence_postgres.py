"""Postgres integration tests for QA persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.qa import PostgresQAPersistence, QAPersistenceError, QAScoreQuery
from app.qa.persistence import QAScoreRecord
from app.supervisor.persistence import (
    InspectionRecord,
    PostgresSupervisorRepository,
    SupervisorDecisionRecord,
)
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]


_NOW = datetime(2026, 5, 22, 12, tzinfo=timezone.utc)


@pytest.fixture
def pg_tenant_id() -> str:
    return "tenant-acme"


def _id(seed: str) -> str:
    return str(uuid.uuid5(uuid.UUID("00000000-0000-0000-0000-000000003200"), seed))


def _inspection(*, tenant_id: str = "tenant-acme") -> InspectionRecord:
    return InspectionRecord(
        inspection_id=_id(f"inspection-{tenant_id}"),
        execution_id=_id(f"execution-{tenant_id}"),
        runtime_instance_id=_id(f"runtime-{tenant_id}"),
        correlation_id=None,
        request_id=None,
        tenant_id=tenant_id,
        tenant_authority_source="header",
        inspection_mode="replay",
        decision=SupervisorDecisionRecord(
            decision_id=_id(f"decision-{tenant_id}"),
            kind="accept",
            aggregate_score=0.9,
            finding_ids=(),
            escalation_ids=(),
            reason="postgres QA fixture",
            decided_at=_NOW.isoformat(),
        ),
        evaluator_names=("execution_completion",),
        started_at=_NOW.isoformat(),
        ended_at=(_NOW + timedelta(milliseconds=5)).isoformat(),
        latency_ms=5.0,
    )


def _score(inspection: InspectionRecord) -> QAScoreRecord:
    return QAScoreRecord(
        score_id=_id(f"qa-score-{inspection.tenant_id}"),
        inspection_id=inspection.inspection_id,
        execution_id=inspection.execution_id,
        tenant_id=str(inspection.tenant_id),
        tenant_authority_source=inspection.tenant_authority_source,
        diagnostic_accuracy=0.9,
        policy_compliance=0.8,
        timeline_integrity=1.0,
        resolution_quality=0.7,
        overall_score=0.85,
        supervisor_decision_kind=inspection.decision.kind,
        finding_count=0,
        evaluation_count=1,
        escalation_count=0,
        scored_at=_NOW.isoformat(),
        metadata={"fixture": "postgres-qa"},
    )


@pytest.mark.asyncio
async def test_postgres_records_and_retrieves_qa_score(
    pg_session: AsyncSession,
) -> None:
    supervisor_repo = PostgresSupervisorRepository(pg_session)
    qa_repo = PostgresQAPersistence(pg_session)
    inspection = _inspection()
    score = _score(inspection)
    await supervisor_repo.record_inspection(inspection)
    await qa_repo.record_score(score, expected_tenant_id="tenant-acme")

    got = await qa_repo.get_score(score.score_id, expected_tenant_id="tenant-acme")
    assert got == score
    by_inspection = await qa_repo.get_score_for_inspection(
        inspection.inspection_id,
        expected_tenant_id="tenant-acme",
    )
    assert by_inspection == score


@pytest.mark.asyncio
async def test_postgres_qa_score_is_write_once(
    pg_session: AsyncSession,
) -> None:
    supervisor_repo = PostgresSupervisorRepository(pg_session)
    qa_repo = PostgresQAPersistence(pg_session)
    inspection = _inspection()
    score = _score(inspection)
    await supervisor_repo.record_inspection(inspection)
    await qa_repo.record_score(score, expected_tenant_id="tenant-acme")

    with pytest.raises(QAPersistenceError, match="write-once"):
        await qa_repo.record_score(score, expected_tenant_id="tenant-acme")


@pytest.mark.asyncio
async def test_postgres_qa_queries_clamp_to_tenant(
    pg_session: AsyncSession,
    pg_seed_session: AsyncSession,
) -> None:
    supervisor_repo = PostgresSupervisorRepository(pg_session)
    qa_repo = PostgresQAPersistence(pg_session)
    seed_supervisor_repo = PostgresSupervisorRepository(pg_seed_session)
    seed_qa_repo = PostgresQAPersistence(pg_seed_session)
    tenant_a = _inspection(tenant_id="tenant-acme")
    tenant_b = _inspection(tenant_id="tenant-other")
    await supervisor_repo.record_inspection(tenant_a)
    await seed_supervisor_repo.record_inspection(tenant_b)
    await qa_repo.record_score(_score(tenant_a), expected_tenant_id="tenant-acme")
    await seed_qa_repo.record_score(
        _score(tenant_b),
        expected_tenant_id="tenant-other",
    )

    page = await qa_repo.list_scores(
        QAScoreQuery(),
        expected_tenant_id="tenant-acme",
    )

    assert page.total == 1
    assert page.items[0].tenant_id == "tenant-acme"
    assert (
        await qa_repo.get_score_for_inspection(
            tenant_b.inspection_id,
            expected_tenant_id="tenant-acme",
        )
        is None
    )
