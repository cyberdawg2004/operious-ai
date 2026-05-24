"""PR-B3 Postgres integration tests for ``PostgresSessionPersistence``.

End-to-end tests against a real Postgres backend through the
``pg_session`` fixture from ``tests/conftest.py``. Every test is
gated by ``requires_postgres`` so the in-memory suite stays green
on developers without ``TEST_DATABASE_URL``.

Two contract layers pinned:

1. **Storage parity** — observable behaviour identical to
   :class:`InMemorySessionPersistence` under the same Protocol
   calls (revision-monotonic session writes, append-only
   contiguous-sequence event writes, tenant-scoped reads).
2. **Persistence durability within the test transaction** —
   records inserted in the test body remain queryable through
   subsequent SELECTs inside the same outer ``BEGIN``.

CI pre-requisite: ``alembic upgrade head`` MUST have been applied
to ``TEST_DATABASE_URL`` before pytest collects these tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.session.enums import (
    SessionContinuityMode,
    SessionCorrelationKind,
    SessionEventKind,
    SessionLifecyclePhase,
    SessionScope,
)
from app.session.exceptions import SessionPersistenceError
from app.session.identity import (
    SessionCorrelationId,
    SessionEventId,
    SessionId,
    SessionLineageId,
)
from app.session.persistence import (
    PostgresSessionPersistence,
    SessionCorrelationQuery,
    SessionCorrelationRecord,
    SessionEventQuery,
    SessionEventRecord,
    SessionQuery,
    SessionRecord,
)
from tests.conftest import requires_postgres, set_pg_rls_tenant

pytestmark = [requires_postgres]


@pytest.fixture
def pg_tenant_id() -> str:
    return "tenant-acme"


# ─── Record builders ─────────────────────────────────────────────────────


def _new_session_id() -> SessionId:
    return SessionId(uuid.uuid4())


def _new_event_id() -> SessionEventId:
    return SessionEventId(uuid.uuid4())


def _new_correlation_id() -> SessionCorrelationId:
    return SessionCorrelationId(uuid.uuid4())


def _new_lineage_id() -> SessionLineageId:
    return SessionLineageId(uuid.uuid4())


def _at(seconds: int = 0) -> datetime:
    return datetime(2026, 5, 19, 9, 0, seconds, tzinfo=timezone.utc)


def _session(
    *,
    session_id: SessionId | None = None,
    tenant_id: str | None = "tenant-acme",
    revision: int = 1,
    sequence_head: int = 0,
) -> SessionRecord:
    sid = session_id or _new_session_id()
    return SessionRecord(
        session_id=sid,
        scope=SessionScope.TENANT,
        external_handle=f"handle-{sid}",
        tenant_id=tenant_id,
        principal_id="principal-test",
        opened_at=_at(),
        lifecycle_phase=SessionLifecyclePhase.ACTIVE,
        lifecycle_recorded_at=_at(),
        lifecycle_reason=None,
        lineage_id=_new_lineage_id(),
        root_session_id=sid,
        parent_session_id=None,
        ancestor_session_ids=(),
        lineage_depth=0,
        sequence_head=sequence_head,
        revision=revision,
    )


def _event(
    *,
    session_id: SessionId,
    sequence: int,
    event_id: SessionEventId | None = None,
) -> SessionEventRecord:
    return SessionEventRecord(
        event_id=event_id or _new_event_id(),
        session_id=session_id,
        sequence=sequence,
        kind=SessionEventKind.OPERATIONAL_OBSERVATION,
        continuity_mode=SessionContinuityMode.SYNCHRONOUS,
        occurred_at=_at(sequence),
        recorded_at=_at(sequence),
    )


def _correlation(
    *,
    session_id: SessionId,
    correlation_id: SessionCorrelationId | None = None,
    external_id: str = "ext-1",
) -> SessionCorrelationRecord:
    return SessionCorrelationRecord(
        correlation_id=correlation_id or _new_correlation_id(),
        session_id=session_id,
        kind=SessionCorrelationKind.EXTERNAL,
        external_id=external_id,
        recorded_at=_at(),
    )


# ─── Write + read round-trips ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_postgres_records_and_retrieves_session(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSessionPersistence(pg_session)
    record = _session()
    await repo.save_session(record)

    got = await repo.get_session(record.session_id)
    assert got is not None
    assert got.session_id == record.session_id
    assert got.tenant_id == "tenant-acme"
    assert got.lifecycle_phase == SessionLifecyclePhase.ACTIVE


@pytest.mark.asyncio
async def test_postgres_records_and_retrieves_event(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSessionPersistence(pg_session)
    session = _session()
    await repo.save_session(session)
    event = _event(session_id=session.session_id, sequence=0)
    await repo.save_event(event)

    got = await repo.get_event(event.event_id)
    assert got is not None
    assert got.session_id == session.session_id
    assert got.sequence == 0


@pytest.mark.asyncio
async def test_postgres_records_and_retrieves_correlation(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSessionPersistence(pg_session)
    session = _session()
    await repo.save_session(session)
    correlation = _correlation(session_id=session.session_id)
    await repo.save_correlation(correlation)

    got = await repo.get_correlation(correlation.correlation_id)
    assert got is not None
    assert got.session_id == session.session_id


# ─── Append-only / monotonic invariants ──────────────────────────────────


@pytest.mark.asyncio
async def test_postgres_rejects_non_monotonic_session_revision(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSessionPersistence(pg_session)
    sid = _new_session_id()
    await repo.save_session(_session(session_id=sid, revision=1))
    with pytest.raises(SessionPersistenceError, match="non-monotonic revision"):
        await repo.save_session(_session(session_id=sid, revision=1))


@pytest.mark.asyncio
async def test_postgres_allows_monotonic_session_revision(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSessionPersistence(pg_session)
    sid = _new_session_id()
    await repo.save_session(_session(session_id=sid, revision=1))
    await repo.save_session(_session(session_id=sid, revision=2))
    got = await repo.get_session(sid)
    assert got is not None
    assert got.revision == 2


@pytest.mark.asyncio
async def test_postgres_event_first_sequence_must_be_zero(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSessionPersistence(pg_session)
    session = _session()
    await repo.save_session(session)
    with pytest.raises(SessionPersistenceError, match="sequence 0"):
        await repo.save_event(_event(session_id=session.session_id, sequence=5))


@pytest.mark.asyncio
async def test_postgres_event_sequence_must_be_contiguous(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSessionPersistence(pg_session)
    session = _session()
    await repo.save_session(session)
    await repo.save_event(_event(session_id=session.session_id, sequence=0))
    with pytest.raises(SessionPersistenceError, match="non-monotonic"):
        await repo.save_event(_event(session_id=session.session_id, sequence=2))


@pytest.mark.asyncio
async def test_postgres_event_duplicate_id_rejected(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSessionPersistence(pg_session)
    session = _session()
    await repo.save_session(session)
    eid = _new_event_id()
    await repo.save_event(
        _event(session_id=session.session_id, sequence=0, event_id=eid)
    )
    # Same id, next valid sequence → still rejected on PK collision.
    with pytest.raises(SessionPersistenceError, match="duplicate event id"):
        await repo.save_event(
            _event(session_id=session.session_id, sequence=1, event_id=eid)
        )


@pytest.mark.asyncio
async def test_postgres_correlation_duplicate_id_rejected(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSessionPersistence(pg_session)
    session = _session()
    await repo.save_session(session)
    cid = _new_correlation_id()
    await repo.save_correlation(
        _correlation(session_id=session.session_id, correlation_id=cid)
    )
    with pytest.raises(SessionPersistenceError, match="duplicate correlation"):
        await repo.save_correlation(
            _correlation(session_id=session.session_id, correlation_id=cid)
        )


# ─── Tenant-scope point reads ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_postgres_get_session_respects_tenant_scope(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSessionPersistence(pg_session)
    session = _session(tenant_id="tenant-acme")
    await repo.save_session(session)

    assert (
        await repo.get_session(
            session.session_id, expected_tenant_id="tenant-acme"
        )
        is not None
    )
    assert (
        await repo.get_session(
            session.session_id, expected_tenant_id="tenant-other"
        )
        is None
    )
    assert await repo.get_session(session.session_id) is not None


@pytest.mark.asyncio
async def test_postgres_get_session_cross_tenant_invisible_to_scoped_reader(
    pg_session: AsyncSession,
    pg_seed_session: AsyncSession,
) -> None:
    repo = PostgresSessionPersistence(pg_session)
    seed_repo = PostgresSessionPersistence(pg_seed_session)
    session = _session(tenant_id="tenant-other")
    await seed_repo.save_session(session)

    assert (
        await repo.get_session(
            session.session_id, expected_tenant_id="tenant-acme"
        )
        is None
    )


@pytest.mark.asyncio
async def test_postgres_get_event_inherits_tenant_scope_from_session(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSessionPersistence(pg_session)
    session = _session(tenant_id="tenant-acme")
    await repo.save_session(session)
    event = _event(session_id=session.session_id, sequence=0)
    await repo.save_event(event)

    assert (
        await repo.get_event(
            event.event_id, expected_tenant_id="tenant-acme"
        )
        is not None
    )
    assert (
        await repo.get_event(
            event.event_id, expected_tenant_id="tenant-other"
        )
        is None
    )


@pytest.mark.asyncio
async def test_postgres_get_correlation_inherits_tenant_scope_from_session(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSessionPersistence(pg_session)
    session = _session(tenant_id="tenant-acme")
    await repo.save_session(session)
    correlation = _correlation(session_id=session.session_id)
    await repo.save_correlation(correlation)

    assert (
        await repo.get_correlation(
            correlation.correlation_id, expected_tenant_id="tenant-acme"
        )
        is not None
    )
    assert (
        await repo.get_correlation(
            correlation.correlation_id, expected_tenant_id="tenant-other"
        )
        is None
    )


# ─── List / query reads ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_postgres_list_sessions_clamps_to_tenant(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSessionPersistence(pg_session)
    tenant_id = f"tenant-acme-{uuid.uuid4()}"
    other_tenant_id = f"tenant-other-{uuid.uuid4()}"
    await set_pg_rls_tenant(pg_session, tenant_id)
    await repo.save_session(_session(tenant_id=tenant_id))
    await repo.save_session(_session(tenant_id=tenant_id))
    await set_pg_rls_tenant(pg_session, other_tenant_id)
    await repo.save_session(_session(tenant_id=other_tenant_id))

    await set_pg_rls_tenant(pg_session, tenant_id)
    page = await repo.list_sessions(
        SessionQuery(), expected_tenant_id=tenant_id
    )
    assert page.total == 2
    assert all(s.tenant_id == tenant_id for s in page.sessions)


@pytest.mark.asyncio
async def test_postgres_list_events_returns_empty_for_cross_tenant(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSessionPersistence(pg_session)
    session = _session(tenant_id="tenant-acme")
    await repo.save_session(session)
    await repo.save_event(_event(session_id=session.session_id, sequence=0))

    page = await repo.list_events(
        SessionEventQuery(session_id=session.session_id),
        expected_tenant_id="tenant-other",
    )
    assert page.total == 0
    assert page.events == ()


@pytest.mark.asyncio
async def test_postgres_list_correlations_clamps_via_parent_session(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSessionPersistence(pg_session)
    tenant_id = f"tenant-acme-{uuid.uuid4()}"
    other_tenant_id = f"tenant-other-{uuid.uuid4()}"
    acme_session = _session(tenant_id=tenant_id)
    other_session = _session(tenant_id=other_tenant_id)
    await set_pg_rls_tenant(pg_session, tenant_id)
    await repo.save_session(acme_session)
    await set_pg_rls_tenant(pg_session, other_tenant_id)
    await repo.save_session(other_session)
    await set_pg_rls_tenant(pg_session, tenant_id)
    await repo.save_correlation(
        _correlation(session_id=acme_session.session_id, external_id="acme-1")
    )
    await set_pg_rls_tenant(pg_session, other_tenant_id)
    await repo.save_correlation(
        _correlation(session_id=other_session.session_id, external_id="other-1")
    )

    await set_pg_rls_tenant(pg_session, tenant_id)
    page = await repo.list_correlations(
        SessionCorrelationQuery(), expected_tenant_id=tenant_id
    )
    assert page.total == 1
    assert page.correlations[0].external_id == "acme-1"


@pytest.mark.asyncio
async def test_postgres_list_events_returns_contiguous_ordered(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSessionPersistence(pg_session)
    session = _session()
    await repo.save_session(session)
    for i in range(3):
        await repo.save_event(
            _event(session_id=session.session_id, sequence=i)
        )

    page = await repo.list_events(
        SessionEventQuery(session_id=session.session_id)
    )
    assert page.total == 3
    assert [e.sequence for e in page.events] == [0, 1, 2]


@pytest.mark.asyncio
async def test_postgres_list_sessions_paginates(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresSessionPersistence(pg_session)
    tenant_id = f"tenant-page-{uuid.uuid4()}"
    await set_pg_rls_tenant(pg_session, tenant_id)
    for _ in range(5):
        await repo.save_session(_session(tenant_id=tenant_id))

    first = await repo.list_sessions(
        SessionQuery(tenant_id=tenant_id, limit=2, offset=0)
    )
    second = await repo.list_sessions(
        SessionQuery(tenant_id=tenant_id, limit=2, offset=2)
    )
    third = await repo.list_sessions(
        SessionQuery(tenant_id=tenant_id, limit=2, offset=4)
    )
    assert first.total == 5
    assert len(first.sessions) == 2
    assert len(second.sessions) == 2
    assert len(third.sessions) == 1
