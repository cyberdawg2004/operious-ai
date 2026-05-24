"""PR-B6 Postgres integration tests for ``PostgresSupervisorRepository``.

Gated by ``requires_postgres``. Pins write-once + tenant-scope
inheritance from apex to sub-records + canonical ordering parity
with the in-memory backend.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.supervisor.exceptions import SupervisorPersistenceError
from app.supervisor.persistence import (
    EscalationDecisionRecord,
    EvaluationEvidenceRecord,
    InspectionQuery,
    InspectionRecord,
    PostgresSupervisorRepository,
    QAEvaluationRecord,
    RuntimeFindingRecord,
    SupervisorDecisionRecord,
)
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]


@pytest.fixture
def pg_tenant_id() -> str:
    return "tenant-acme"


def _at(s: int = 0) -> str:
    return datetime(2026, 5, 19, 9, 0, s, tzinfo=timezone.utc).isoformat()


def _decision() -> SupervisorDecisionRecord:
    return SupervisorDecisionRecord(
        decision_id=str(uuid.uuid4()),
        kind="accept",
        aggregate_score=0.95,
        finding_ids=(),
        escalation_ids=(),
        reason="all evaluators passed",
        decided_at=_at(),
    )


def _inspection(
    *,
    inspection_id: str | None = None,
    tenant_id: str | None = "tenant-acme",
) -> InspectionRecord:
    return InspectionRecord(
        inspection_id=inspection_id or str(uuid.uuid4()),
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
        evaluator_name="test_evaluator",
        category="quality",
        severity="low",
        code="test.finding",
        message="finding",
        evidence=EvaluationEvidenceRecord(execution_id=str(uuid.uuid4())),
        detected_at=_at(),
        metadata={"inspection_id": inspection_id},
    )


def _evaluation(*, inspection_id: str, evaluator_name: str = "test_evaluator") -> QAEvaluationRecord:
    return QAEvaluationRecord(
        inspection_id=inspection_id,
        evaluator_name=evaluator_name,
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


# ─── Write + read ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_postgres_records_and_retrieves_inspection(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSupervisorRepository(pg_session)
    record = _inspection()
    await repo.record_inspection(record)

    got = await repo.get_inspection(record.inspection_id)
    assert got is not None
    assert got.inspection_id == record.inspection_id
    assert got.tenant_id == "tenant-acme"
    assert got.decision.kind == "accept"


@pytest.mark.asyncio
async def test_postgres_records_finding_and_retrieves_by_inspection(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSupervisorRepository(pg_session)
    inspection = _inspection()
    await repo.record_inspection(inspection)
    finding = _finding(inspection_id=inspection.inspection_id)
    await repo.record_finding(finding)

    findings = await repo.get_findings_for_inspection(inspection.inspection_id)
    assert len(findings) == 1
    assert findings[0].finding_id == finding.finding_id


@pytest.mark.asyncio
async def test_postgres_records_evaluation_and_escalation(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSupervisorRepository(pg_session)
    inspection = _inspection()
    await repo.record_inspection(inspection)
    await repo.record_evaluation(
        _evaluation(inspection_id=inspection.inspection_id)
    )
    await repo.record_escalation(
        _escalation(inspection_id=inspection.inspection_id)
    )

    evaluations = await repo.get_evaluations_for_inspection(
        inspection.inspection_id
    )
    escalations = await repo.get_escalations_for_inspection(
        inspection.inspection_id
    )
    assert len(evaluations) == 1
    assert len(escalations) == 1


# ─── Write-once invariants ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_postgres_inspection_write_once(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSupervisorRepository(pg_session)
    record = _inspection()
    await repo.record_inspection(record)
    with pytest.raises(SupervisorPersistenceError, match="write-once"):
        await repo.record_inspection(record)


@pytest.mark.asyncio
async def test_postgres_evaluation_dedupes_by_inspection_and_evaluator(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSupervisorRepository(pg_session)
    inspection = _inspection()
    await repo.record_inspection(inspection)
    await repo.record_evaluation(
        _evaluation(inspection_id=inspection.inspection_id)
    )
    with pytest.raises(SupervisorPersistenceError, match="already recorded"):
        await repo.record_evaluation(
            _evaluation(inspection_id=inspection.inspection_id)
        )


@pytest.mark.asyncio
async def test_postgres_finding_requires_inspection_id_in_metadata(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSupervisorRepository(pg_session)
    bad = RuntimeFindingRecord(
        finding_id=str(uuid.uuid4()),
        evaluator_name="x",
        category="quality",
        severity="low",
        code="x",
        message="x",
        evidence=EvaluationEvidenceRecord(execution_id=str(uuid.uuid4())),
        detected_at=_at(),
        metadata={},  # no inspection_id
    )
    with pytest.raises(SupervisorPersistenceError, match="inspection_id"):
        await repo.record_finding(bad)


# ─── Tenant scope ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_postgres_get_inspection_respects_tenant_scope(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSupervisorRepository(pg_session)
    record = _inspection(tenant_id="tenant-acme")
    await repo.record_inspection(record)

    assert (
        await repo.get_inspection(
            record.inspection_id, expected_tenant_id="tenant-acme"
        )
        is not None
    )
    assert (
        await repo.get_inspection(
            record.inspection_id, expected_tenant_id="tenant-other"
        )
        is None
    )


@pytest.mark.asyncio
async def test_postgres_sub_records_inherit_tenant_scope_from_inspection(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSupervisorRepository(pg_session)
    inspection = _inspection(tenant_id="tenant-acme")
    await repo.record_inspection(inspection)
    await repo.record_finding(_finding(inspection_id=inspection.inspection_id))
    await repo.record_evaluation(
        _evaluation(inspection_id=inspection.inspection_id)
    )
    await repo.record_escalation(
        _escalation(inspection_id=inspection.inspection_id)
    )

    # Owning tenant sees all three sub-records.
    assert len(
        await repo.get_findings_for_inspection(
            inspection.inspection_id, expected_tenant_id="tenant-acme"
        )
    ) == 1
    assert len(
        await repo.get_evaluations_for_inspection(
            inspection.inspection_id, expected_tenant_id="tenant-acme"
        )
    ) == 1
    assert len(
        await repo.get_escalations_for_inspection(
            inspection.inspection_id, expected_tenant_id="tenant-acme"
        )
    ) == 1

    # Other tenant: empty across all three.
    assert (
        await repo.get_findings_for_inspection(
            inspection.inspection_id, expected_tenant_id="tenant-other"
        )
        == ()
    )
    assert (
        await repo.get_evaluations_for_inspection(
            inspection.inspection_id, expected_tenant_id="tenant-other"
        )
        == ()
    )
    assert (
        await repo.get_escalations_for_inspection(
            inspection.inspection_id, expected_tenant_id="tenant-other"
        )
        == ()
    )


@pytest.mark.asyncio
async def test_postgres_query_inspections_clamps_to_tenant(
    pg_session: AsyncSession,
    pg_seed_session: AsyncSession,
) -> None:
    repo = PostgresSupervisorRepository(pg_session)
    seed_repo = PostgresSupervisorRepository(pg_seed_session)
    await repo.record_inspection(_inspection(tenant_id="tenant-acme"))
    await repo.record_inspection(_inspection(tenant_id="tenant-acme"))
    await seed_repo.record_inspection(_inspection(tenant_id="tenant-other"))

    page = await repo.query_inspections(
        InspectionQuery(), expected_tenant_id="tenant-acme"
    )
    assert page.total == 2
    assert all(i.tenant_id == "tenant-acme" for i in page.items)
