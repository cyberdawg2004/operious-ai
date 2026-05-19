"""PR-B2 Postgres integration tests for ``PostgresGovernanceRepository``.

End-to-end tests that exercise the real Postgres backend through
the ``pg_session`` fixture from ``tests/conftest.py``. Every test
in this module is gated by the ``requires_postgres`` marker — when
``TEST_DATABASE_URL`` is unset the entire module skips, so the
in-memory test suite remains green on developers without a local
Postgres.

The tests pin two contracts:

1. **Storage parity** — the Postgres backend produces the same
   observable behaviour as :class:`InMemoryGovernanceRepository`
   under the same Protocol calls. Anything the in-memory
   substrate guarantees, the Postgres substrate MUST also
   guarantee (write-once, tenant-scoped point reads, filtered
   queries, pagination).
2. **Persistence durability** — records survive a flush. Even
   though the outer transaction is rolled back at fixture
   teardown, within the test the records are queryable through
   subsequent SELECTs.

CI/operator pre-requisite: ``alembic upgrade head`` MUST have been
applied to the database pointed at by ``TEST_DATABASE_URL`` before
pytest collects these tests. Without that, every test in this
module raises a ``ProgrammingError`` on the first INSERT.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.governance.persistence import (
    DecisionQuery,
    EnforcementActionRecord,
    GovernanceDecisionRecord,
    GovernanceTraceRecord,
    PostgresGovernanceRepository,
)
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]


# ─── Test fixtures (record builders) ─────────────────────────────────────


def _decision(
    *,
    decision_id: str | None = None,
    tenant_id: str | None = "tenant-acme",
    decided_at: datetime | None = None,
) -> GovernanceDecisionRecord:
    return GovernanceDecisionRecord(
        decision_id=decision_id or str(uuid.uuid4()),
        decision="allow",
        stage="pre_retrieval",
        policy_chain_id="postgres_test.chain",
        reason="ok",
        decided_at=(
            decided_at or datetime(2026, 5, 19, 9, tzinfo=timezone.utc)
        ).isoformat(),
        tenant_id=tenant_id,
        governance_version="postgres-test/1.0",
    )


def _trace(
    *,
    decision_id: str,
    tenant_id: str | None = "tenant-acme",
) -> GovernanceTraceRecord:
    return GovernanceTraceRecord(
        decision_id=decision_id,
        request_id=None,
        correlation_id=None,
        stage="pre_retrieval",
        action="retrieve",
        resource="docs/*",
        actor="agent:test",
        tenant_id=tenant_id,
        subject_kind="generic",
        started_at="2026-05-19T09:00:00+00:00",
        ended_at="2026-05-19T09:00:00.000100+00:00",
        latency_ms=0.1,
        status="ok",
        final_decision="allow",
        policy_chain_id="postgres_test.chain",
        rule_count=0,
        violation_count=0,
        restriction_count=0,
        enforcement_handler=None,
        enforcement_status=None,
        enforcement_latency_ms=None,
    )


def _action(
    *,
    decision_id: str,
    action_id: str | None = None,
) -> EnforcementActionRecord:
    return EnforcementActionRecord(
        action_id=action_id or str(uuid.uuid4()),
        handler_name="allow",
        decision_id=decision_id,
        outcome="applied",
        applied_at="2026-05-19T09:00:00.001000+00:00",
    )


# ─── Write + read round-trip ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_postgres_records_and_retrieves_decision(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresGovernanceRepository(pg_session)
    record = _decision()
    await repo.record_decision(record)

    got = await repo.get_decision(record.decision_id)
    assert got is not None
    assert got.decision_id == record.decision_id
    assert got.decision == "allow"
    assert got.tenant_id == "tenant-acme"
    assert got.governance_version == "postgres-test/1.0"


@pytest.mark.asyncio
async def test_postgres_records_and_retrieves_trace(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresGovernanceRepository(pg_session)
    decision = _decision()
    await repo.record_decision(decision)
    await repo.record_trace(_trace(decision_id=decision.decision_id))

    got = await repo.get_trace(decision.decision_id)
    assert got is not None
    assert got.decision_id == decision.decision_id
    assert got.action == "retrieve"


@pytest.mark.asyncio
async def test_postgres_records_and_retrieves_enforcement_action(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresGovernanceRepository(pg_session)
    decision = _decision()
    await repo.record_decision(decision)
    action = _action(decision_id=decision.decision_id)
    await repo.record_enforcement_action(action)

    actions = await repo.get_enforcement_actions(decision.decision_id)
    assert len(actions) == 1
    assert actions[0].action_id == action.action_id


# ─── Write-once invariant ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_postgres_decision_write_once(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresGovernanceRepository(pg_session)
    record = _decision()
    await repo.record_decision(record)
    with pytest.raises(ValueError, match="write-once"):
        await repo.record_decision(record)


@pytest.mark.asyncio
async def test_postgres_trace_write_once(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresGovernanceRepository(pg_session)
    decision = _decision()
    await repo.record_decision(decision)
    trace = _trace(decision_id=decision.decision_id)
    await repo.record_trace(trace)
    with pytest.raises(ValueError, match="write-once"):
        await repo.record_trace(trace)


# ─── Tenant-scope point reads ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_postgres_get_decision_respects_tenant_scope(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresGovernanceRepository(pg_session)
    acme = _decision(tenant_id="tenant-acme")
    await repo.record_decision(acme)

    # Owning tenant sees the row.
    assert (
        await repo.get_decision(
            acme.decision_id, expected_tenant_id="tenant-acme"
        )
        is not None
    )
    # Other tenant cannot see the row.
    assert (
        await repo.get_decision(
            acme.decision_id, expected_tenant_id="tenant-other"
        )
        is None
    )
    # Admin path sees the row.
    assert await repo.get_decision(acme.decision_id) is not None


@pytest.mark.asyncio
async def test_postgres_get_decision_tenantless_invisible_to_scoped_reader(
    pg_session: AsyncSession,
) -> None:
    """System-level (tenantless) decisions persist with
    ``tenant_id IS NULL``; a tenant-scoped read MUST NOT see them.
    Postgres three-valued logic on ``NULL = $X`` returns unknown,
    which the WHERE clause filters out — the row is invisible."""
    repo = PostgresGovernanceRepository(pg_session)
    system_decision = _decision(tenant_id=None)
    await repo.record_decision(system_decision)

    # Tenant-scoped read: NULL tenant_id is invisible.
    assert (
        await repo.get_decision(
            system_decision.decision_id, expected_tenant_id="tenant-acme"
        )
        is None
    )
    # Admin path: visible (substrate-internal reconstruction).
    got = await repo.get_decision(system_decision.decision_id)
    assert got is not None
    assert got.tenant_id is None


@pytest.mark.asyncio
async def test_postgres_get_enforcement_actions_inherits_scope_from_decision(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresGovernanceRepository(pg_session)
    decision = _decision(tenant_id="tenant-acme")
    await repo.record_decision(decision)
    await repo.record_enforcement_action(
        _action(decision_id=decision.decision_id)
    )

    # Owning tenant sees the actions.
    owned = await repo.get_enforcement_actions(
        decision.decision_id, expected_tenant_id="tenant-acme"
    )
    assert len(owned) == 1

    # Cross-tenant: empty.
    other = await repo.get_enforcement_actions(
        decision.decision_id, expected_tenant_id="tenant-other"
    )
    assert other == ()


# ─── Paginated queries ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_postgres_query_decisions_filters_by_tenant(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresGovernanceRepository(pg_session)
    base = datetime(2026, 5, 19, 9, tzinfo=timezone.utc)
    await repo.record_decision(_decision(tenant_id="tenant-acme", decided_at=base))
    await repo.record_decision(_decision(tenant_id="tenant-acme", decided_at=base.replace(second=1)))
    await repo.record_decision(_decision(tenant_id="tenant-other", decided_at=base.replace(second=2)))

    page = await repo.query_decisions(
        DecisionQuery(tenant_id="tenant-acme", limit=10)
    )
    assert page.total == 2
    assert all(r.tenant_id == "tenant-acme" for r in page.items)


@pytest.mark.asyncio
async def test_postgres_query_decisions_paginates(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresGovernanceRepository(pg_session)
    base = datetime(2026, 5, 19, 9, tzinfo=timezone.utc)
    for i in range(5):
        await repo.record_decision(
            _decision(decided_at=base.replace(second=i))
        )

    page = await repo.query_decisions(DecisionQuery(limit=2, offset=0))
    assert page.total == 5
    assert len(page.items) == 2

    next_page = await repo.query_decisions(
        DecisionQuery(limit=2, offset=2)
    )
    assert next_page.total == 5
    assert len(next_page.items) == 2

    last_page = await repo.query_decisions(
        DecisionQuery(limit=2, offset=4)
    )
    assert last_page.total == 5
    assert len(last_page.items) == 1


@pytest.mark.asyncio
async def test_postgres_query_traces_filters_by_request_id(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresGovernanceRepository(pg_session)
    base = datetime(2026, 5, 19, 9, tzinfo=timezone.utc)
    d_a = _decision(decided_at=base)
    d_b = _decision(decided_at=base.replace(second=1))
    await repo.record_decision(d_a)
    await repo.record_decision(d_b)
    trace_a = GovernanceTraceRecord(
        decision_id=d_a.decision_id,
        request_id="req-1",
        correlation_id=None,
        stage="pre_retrieval",
        action="retrieve",
        resource="docs/*",
        actor="agent:test",
        tenant_id="tenant-acme",
        subject_kind="generic",
        started_at=base.isoformat(),
        ended_at=base.isoformat(),
        latency_ms=0.0,
        status="ok",
        final_decision="allow",
        policy_chain_id="t",
        rule_count=0,
        violation_count=0,
        restriction_count=0,
        enforcement_handler=None,
        enforcement_status=None,
        enforcement_latency_ms=None,
    )
    trace_b = GovernanceTraceRecord(
        decision_id=d_b.decision_id,
        request_id="req-2",
        correlation_id=None,
        stage="pre_retrieval",
        action="retrieve",
        resource="docs/*",
        actor="agent:test",
        tenant_id="tenant-acme",
        subject_kind="generic",
        started_at=base.isoformat(),
        ended_at=base.isoformat(),
        latency_ms=0.0,
        status="ok",
        final_decision="allow",
        policy_chain_id="t",
        rule_count=0,
        violation_count=0,
        restriction_count=0,
        enforcement_handler=None,
        enforcement_status=None,
        enforcement_latency_ms=None,
    )
    await repo.record_trace(trace_a)
    await repo.record_trace(trace_b)

    page = await repo.query_traces(
        DecisionQuery(request_id="req-1", limit=10)
    )
    assert page.total == 1
    assert page.items[0].decision_id == d_a.decision_id
