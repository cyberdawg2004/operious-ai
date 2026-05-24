"""PR-B5 Postgres integration tests for ``PostgresArbitrationPersistence``.

Gated by ``requires_postgres``. Pins write-once + tenant-scoped
reads + canonical ordering parity with the in-memory backend.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.arbitration.enums import (
    ArbitrationAuthorityLevel,
    ArbitrationConflictKind,
    ArbitrationOutcome,
)
from app.arbitration.exceptions import ArbitrationPersistenceError
from app.arbitration.identity import (
    ArbitrationCaseId,
    ArbitrationChainId,
    ArbitrationConflictId,
    ArbitrationEvaluationId,
)
from app.arbitration.persistence import (
    ArbitrationConflictRecord,
    ArbitrationFindingRecord,
    ArbitrationQuery,
    ArbitrationRecord,
    PostgresArbitrationPersistence,
)
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]


@pytest.fixture
def pg_tenant_id() -> str:
    return "tenant-acme"


def _at(s: int = 0) -> datetime:
    return datetime(2026, 5, 19, 9, 0, s, tzinfo=timezone.utc)


def _record(
    *,
    evaluation_id: ArbitrationEvaluationId | None = None,
    runtime_instance_id: uuid.UUID | None = None,
    sequence: int = 0,
    tenant_id: str | None = "tenant-acme",
    correlation_id: str | None = None,
    outcome: ArbitrationOutcome = ArbitrationOutcome.ARBITRATION_RESOLVED,
) -> ArbitrationRecord:
    eid = evaluation_id or ArbitrationEvaluationId(uuid.uuid4())
    return ArbitrationRecord(
        evaluation_id=eid,
        chain_id=ArbitrationChainId(uuid.uuid4()),
        case_id=ArbitrationCaseId(uuid.uuid4()),
        runtime_instance_id=runtime_instance_id or uuid.uuid4(),
        sequence=sequence,
        outcome=outcome,
        prevailing_authority_level=ArbitrationAuthorityLevel.GOVERNANCE,
        prevailing_authority_source_substrate="governance",
        prevailing_authority_source_id="signal-1",
        prevailing_authority_verdict="allow",
        reason="resolved",
        evaluator_names=("authority_precedence",),
        findings=(
            ArbitrationFindingRecord(
                finding_id=uuid.uuid4(),
                evaluator_name="authority_precedence",
                outcome_hint=outcome,
                code="arbitration.authority_precedence_applied",
                message="precedence applied",
                detected_at=_at(),
                related_conflict_id=None,
                related_deadlock_witness_id=None,
                authority=ArbitrationAuthorityLevel.GOVERNANCE,
            ),
        ),
        conflicts=(),
        deadlock_witnesses=(),
        signal_count=1,
        recommendation_count=0,
        iteration_count=1,
        max_iterations=5,
        correlation_id=correlation_id,
        request_id=None,
        tenant_id=tenant_id,
        started_at=_at(sequence),
        ended_at=_at(sequence),
        latency_ms=0.5,
        error=None,
    )


# ─── Write + read ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_postgres_saves_and_retrieves_record(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresArbitrationPersistence(pg_session)
    record = _record()
    await repo.save(record)

    got = await repo.get(record.evaluation_id)
    assert got is not None
    assert got.evaluation_id == record.evaluation_id
    assert got.outcome == ArbitrationOutcome.ARBITRATION_RESOLVED
    assert got.tenant_id == "tenant-acme"
    assert len(got.findings) == 1
    assert got.findings[0].code == "arbitration.authority_precedence_applied"


@pytest.mark.asyncio
async def test_postgres_record_write_once(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresArbitrationPersistence(pg_session)
    record = _record()
    await repo.save(record)
    with pytest.raises(ArbitrationPersistenceError, match="duplicate"):
        await repo.save(record)


@pytest.mark.asyncio
async def test_postgres_record_preserves_nested_conflict(
    pg_session: AsyncSession,
) -> None:
    """Nested ArbitrationConflictRecord round-trips through JSONB."""
    repo = PostgresArbitrationPersistence(pg_session)
    base = _record()
    conflict_id = ArbitrationConflictId(uuid.uuid4())
    record = dataclasses.replace(
        base,
        conflicts=(
            ArbitrationConflictRecord(
                conflict_id=conflict_id,
                kind=ArbitrationConflictKind.AUTHORISATION_CONFLICT,
                participants=("signal-1", "signal-2"),
                participant_authorities=(
                    ArbitrationAuthorityLevel.GOVERNANCE,
                    ArbitrationAuthorityLevel.POLICY,
                ),
                summary="A and B disagree",
            ),
        ),
    )
    await repo.save(record)

    got = await repo.get(record.evaluation_id)
    assert got is not None
    assert len(got.conflicts) == 1
    assert got.conflicts[0].conflict_id == conflict_id
    assert got.conflicts[0].kind == ArbitrationConflictKind.AUTHORISATION_CONFLICT


# ─── Tenant scope ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_postgres_get_respects_tenant_scope(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresArbitrationPersistence(pg_session)
    record = _record(tenant_id="tenant-acme")
    await repo.save(record)

    assert (
        await repo.get(
            record.evaluation_id, expected_tenant_id="tenant-acme"
        )
        is not None
    )
    assert (
        await repo.get(
            record.evaluation_id, expected_tenant_id="tenant-other"
        )
        is None
    )
    assert await repo.get(record.evaluation_id) is not None


@pytest.mark.asyncio
async def test_postgres_get_tenantless_invisible_to_scoped_reader(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresArbitrationPersistence(pg_session)
    record = _record(tenant_id=None)
    await repo.save(record)

    assert (
        await repo.get(
            record.evaluation_id, expected_tenant_id="tenant-acme"
        )
        is None
    )
    assert await repo.get(record.evaluation_id) is not None


@pytest.mark.asyncio
async def test_postgres_list_records_clamps_to_tenant(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresArbitrationPersistence(pg_session)
    await repo.save(_record(tenant_id="tenant-acme"))
    await repo.save(_record(tenant_id="tenant-acme"))
    await repo.save(_record(tenant_id="tenant-other"))

    page = await repo.list_records(
        ArbitrationQuery(), expected_tenant_id="tenant-acme"
    )
    assert page.total == 2
    assert all(r.tenant_id == "tenant-acme" for r in page.records)


# ─── Ordering + filters ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_postgres_list_records_orders_by_runtime_seq(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresArbitrationPersistence(pg_session)
    runtime = uuid.uuid4()
    await repo.save(_record(runtime_instance_id=runtime, sequence=2))
    await repo.save(_record(runtime_instance_id=runtime, sequence=0))
    await repo.save(_record(runtime_instance_id=runtime, sequence=1))

    page = await repo.list_records(ArbitrationQuery())
    seqs = [r.sequence for r in page.records if r.runtime_instance_id == runtime]
    assert seqs == [0, 1, 2]


@pytest.mark.asyncio
async def test_postgres_list_records_filters_by_outcome(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresArbitrationPersistence(pg_session)
    await repo.save(_record(outcome=ArbitrationOutcome.ARBITRATION_RESOLVED))
    await repo.save(_record(outcome=ArbitrationOutcome.ARBITRATION_CONFLICT))

    page = await repo.list_records(
        ArbitrationQuery(outcome=ArbitrationOutcome.ARBITRATION_CONFLICT)
    )
    assert page.total == 1
    assert page.records[0].outcome == ArbitrationOutcome.ARBITRATION_CONFLICT
