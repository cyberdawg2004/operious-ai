"""PR-B4 Postgres integration tests for ``PostgresCoordinationPersistence``.

Gated by ``requires_postgres``; skipped when ``TEST_DATABASE_URL``
is unset so the in-memory suite stays green on developers without
a local Postgres.

Contracts pinned:

* Write-once envelope records (duplicate ``coordination_id`` raises
  :class:`CoordinationPersistenceError`).
* Tenant-scoped point + query reads.
* Tenantless envelopes invisible to scoped reads (NULL excluded via
  SQL three-valued logic).
* Canonical ``(runtime_instance_id, sequence)`` ordering.
* Pagination + filter composition.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.coordination.exceptions import CoordinationPersistenceError
from app.coordination.persistence import (
    CoordinationQuery,
    CoordinationRecord,
    PostgresCoordinationPersistence,
)
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]


@pytest.fixture
def pg_tenant_id() -> str:
    return "tenant-acme"


def _at(s: int = 0) -> str:
    return datetime(2026, 5, 19, 9, 0, s, tzinfo=timezone.utc).isoformat()


def _envelope(
    *,
    coordination_id: str | None = None,
    sequence: int = 0,
    runtime_instance_id: str | None = None,
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
        sequence=sequence,
        runtime_instance_id=runtime_instance_id or str(uuid.uuid4()),
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
        created_at=_at(sequence),
        dispatched_at=_at(sequence),
    )


# ─── Write + read ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_postgres_records_and_retrieves_envelope(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresCoordinationPersistence(pg_session)
    record = _envelope()
    await repo.record_envelope(record)

    got = await repo.get_envelope(record.coordination_id)
    assert got is not None
    assert got.coordination_id == record.coordination_id
    assert got.tenant_id == "tenant-acme"
    assert got.payload_body == {"action": "noop"}


@pytest.mark.asyncio
async def test_postgres_envelope_write_once(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresCoordinationPersistence(pg_session)
    record = _envelope()
    await repo.record_envelope(record)
    with pytest.raises(CoordinationPersistenceError, match="write-once"):
        await repo.record_envelope(record)


# ─── Tenant scope ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_postgres_get_envelope_respects_tenant_scope(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresCoordinationPersistence(pg_session)
    record = _envelope(tenant_id="tenant-acme")
    await repo.record_envelope(record)

    assert (
        await repo.get_envelope(
            record.coordination_id, expected_tenant_id="tenant-acme"
        )
        is not None
    )
    assert (
        await repo.get_envelope(
            record.coordination_id, expected_tenant_id="tenant-other"
        )
        is None
    )
    assert await repo.get_envelope(record.coordination_id) is not None


@pytest.mark.asyncio
async def test_postgres_get_envelope_cross_tenant_invisible_to_scoped_reader(
    pg_session: AsyncSession,
    pg_seed_session: AsyncSession,
) -> None:
    repo = PostgresCoordinationPersistence(pg_session)
    seed_repo = PostgresCoordinationPersistence(pg_seed_session)
    record = _envelope(tenant_id="tenant-other")
    await seed_repo.record_envelope(record)

    assert (
        await repo.get_envelope(
            record.coordination_id, expected_tenant_id="tenant-acme"
        )
        is None
    )


@pytest.mark.asyncio
async def test_postgres_query_envelopes_clamps_to_tenant(
    pg_session: AsyncSession,
    pg_seed_session: AsyncSession,
) -> None:
    repo = PostgresCoordinationPersistence(pg_session)
    seed_repo = PostgresCoordinationPersistence(pg_seed_session)
    await repo.record_envelope(_envelope(tenant_id="tenant-acme"))
    await repo.record_envelope(_envelope(tenant_id="tenant-acme"))
    await seed_repo.record_envelope(_envelope(tenant_id="tenant-other"))

    page = await repo.query_envelopes(
        CoordinationQuery(), expected_tenant_id="tenant-acme"
    )
    assert page.total == 2
    assert all(r.tenant_id == "tenant-acme" for r in page.items)


# ─── Ordering + pagination ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_postgres_query_envelopes_orders_by_runtime_seq(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresCoordinationPersistence(pg_session)
    runtime = str(uuid.uuid4())
    await repo.record_envelope(
        _envelope(runtime_instance_id=runtime, sequence=2)
    )
    await repo.record_envelope(
        _envelope(runtime_instance_id=runtime, sequence=0)
    )
    await repo.record_envelope(
        _envelope(runtime_instance_id=runtime, sequence=1)
    )

    page = await repo.query_envelopes(
        CoordinationQuery(runtime_instance_id=runtime)
    )
    assert [r.sequence for r in page.items] == [0, 1, 2]


@pytest.mark.asyncio
async def test_postgres_query_envelopes_filters_by_correlation(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresCoordinationPersistence(pg_session)
    target = "corr-target"
    await repo.record_envelope(_envelope(correlation_id=target))
    await repo.record_envelope(_envelope(correlation_id="corr-other"))

    page = await repo.query_envelopes(
        CoordinationQuery(correlation_id=target)
    )
    assert page.total == 1
    assert page.items[0].correlation_id == target


@pytest.mark.asyncio
async def test_postgres_query_envelopes_paginates(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresCoordinationPersistence(pg_session)
    runtime = str(uuid.uuid4())
    for i in range(5):
        await repo.record_envelope(
            _envelope(runtime_instance_id=runtime, sequence=i)
        )

    first = await repo.query_envelopes(
        CoordinationQuery(runtime_instance_id=runtime, limit=2, offset=0)
    )
    second = await repo.query_envelopes(
        CoordinationQuery(runtime_instance_id=runtime, limit=2, offset=2)
    )
    last = await repo.query_envelopes(
        CoordinationQuery(runtime_instance_id=runtime, limit=2, offset=4)
    )
    assert first.total == 5
    assert len(first.items) == 2
    assert [r.sequence for r in first.items] == [0, 1]
    assert [r.sequence for r in second.items] == [2, 3]
    assert [r.sequence for r in last.items] == [4]
