"""`InMemorySessionPersistence` discipline tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.session.enums import (
    SessionContinuityMode,
    SessionCorrelationKind,
    SessionEventKind,
    SessionLifecyclePhase,
    SessionScope,
)
from app.session.exceptions import SessionPersistenceError
from app.session.identity import (
    derive_event_id,
    derive_lineage_id,
    generate_correlation_id,
    generate_session_id,
)
from app.session.persistence.memory import (
    InMemorySessionPersistence,
)
from app.session.persistence.models import (
    SessionCorrelationQuery,
    SessionEventQuery,
    SessionQuery,
)
from app.session.persistence.records import (
    SessionCorrelationRecord,
    SessionEventRecord,
    SessionRecord,
)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _session_record(
    *, revision: int = 1, sid=None, opened_at: datetime | None = None
) -> SessionRecord:
    sid = sid or generate_session_id()
    return SessionRecord(
        session_id=sid,
        scope=SessionScope.TENANT,
        external_handle="x",
        tenant_id="t1",
        principal_id="p1",
        opened_at=opened_at or _now(),
        lifecycle_phase=SessionLifecyclePhase.INITIATED,
        lifecycle_recorded_at=opened_at or _now(),
        lifecycle_reason=None,
        lineage_id=derive_lineage_id(root_session_id=sid),
        root_session_id=sid,
        parent_session_id=None,
        ancestor_session_ids=(),
        lineage_depth=0,
        sequence_head=-1,
        revision=revision,
    )


def _event_record(
    *, sid, sequence: int, idempotency_key: str | None = None
) -> SessionEventRecord:
    return SessionEventRecord(
        event_id=derive_event_id(session_id=sid, sequence=sequence),
        session_id=sid,
        sequence=sequence,
        kind=SessionEventKind.OPERATIONAL_OBSERVATION
        if sequence > 0
        else SessionEventKind.SESSION_OPENED,
        continuity_mode=SessionContinuityMode.SYNCHRONOUS,
        occurred_at=_now(),
        recorded_at=_now(),
        idempotency_key=idempotency_key,
    )


def _correlation_record(*, sid) -> SessionCorrelationRecord:
    return SessionCorrelationRecord(
        correlation_id=generate_correlation_id(),
        session_id=sid,
        kind=SessionCorrelationKind.COORDINATION,
        external_id="coord-1",
        recorded_at=_now(),
    )


@pytest.mark.asyncio
async def test_session_revision_must_be_monotonic() -> None:
    store = InMemorySessionPersistence()
    sid = generate_session_id()
    await store.save_session(_session_record(revision=1, sid=sid))
    with pytest.raises(SessionPersistenceError):
        await store.save_session(
            _session_record(revision=1, sid=sid)
        )
    await store.save_session(_session_record(revision=2, sid=sid))


@pytest.mark.asyncio
async def test_event_save_is_append_only() -> None:
    store = InMemorySessionPersistence()
    sid = generate_session_id()
    await store.save_event(_event_record(sid=sid, sequence=0))
    with pytest.raises(SessionPersistenceError):
        await store.save_event(_event_record(sid=sid, sequence=0))


@pytest.mark.asyncio
async def test_event_save_enforces_monotonic_sequence() -> None:
    store = InMemorySessionPersistence()
    sid = generate_session_id()
    await store.save_event(_event_record(sid=sid, sequence=0))
    with pytest.raises(SessionPersistenceError):
        await store.save_event(_event_record(sid=sid, sequence=2))


@pytest.mark.asyncio
async def test_event_idempotency_key_is_unique_per_session() -> None:
    store = InMemorySessionPersistence()
    sid = generate_session_id()
    key = "execution.exec-1.attempt.attempt-1.event.completed"
    await store.save_session(_session_record(sid=sid))
    await store.save_event(_event_record(sid=sid, sequence=0))
    record = _event_record(
        sid=sid, sequence=1, idempotency_key=key
    )
    await store.save_event(record)

    replay = await store.get_event_by_idempotency_key(
        session_id=sid,
        idempotency_key=key,
        expected_tenant_id="t1",
    )
    assert replay == record

    with pytest.raises(SessionPersistenceError):
        await store.save_event(
            _event_record(
                sid=sid, sequence=2, idempotency_key=key
            )
        )


@pytest.mark.asyncio
async def test_event_first_must_have_sequence_zero() -> None:
    store = InMemorySessionPersistence()
    sid = generate_session_id()
    with pytest.raises(SessionPersistenceError):
        await store.save_event(_event_record(sid=sid, sequence=1))


@pytest.mark.asyncio
async def test_correlation_save_rejects_duplicates() -> None:
    store = InMemorySessionPersistence()
    sid = generate_session_id()
    record = _correlation_record(sid=sid)
    await store.save_correlation(record)
    with pytest.raises(SessionPersistenceError):
        await store.save_correlation(record)


@pytest.mark.asyncio
async def test_list_events_orders_by_sequence() -> None:
    store = InMemorySessionPersistence()
    sid = generate_session_id()
    await store.save_event(_event_record(sid=sid, sequence=0))
    await store.save_event(_event_record(sid=sid, sequence=1))
    await store.save_event(_event_record(sid=sid, sequence=2))
    page = await store.list_events(SessionEventQuery(session_id=sid))
    assert [e.sequence for e in page.events] == [0, 1, 2]


@pytest.mark.asyncio
async def test_list_sessions_filters_and_pages() -> None:
    store = InMemorySessionPersistence()
    sid_a = generate_session_id()
    sid_b = generate_session_id()
    await store.save_session(_session_record(sid=sid_a))
    await store.save_session(_session_record(sid=sid_b))
    page = await store.list_sessions(
        SessionQuery(tenant_id="t1", limit=1)
    )
    assert page.total == 2
    assert len(page.sessions) == 1


@pytest.mark.asyncio
async def test_list_sessions_orders_newest_first() -> None:
    store = InMemorySessionPersistence()
    older = _session_record(opened_at=_now() - timedelta(minutes=5))
    newer = _session_record(opened_at=_now())
    await store.save_session(older)
    await store.save_session(newer)

    page = await store.list_sessions(SessionQuery(tenant_id="t1", limit=1))

    assert page.total == 2
    assert page.sessions[0].session_id == newer.session_id


@pytest.mark.asyncio
async def test_list_correlations_sorts_deterministically() -> None:
    store = InMemorySessionPersistence()
    sid = generate_session_id()
    rec_a = _correlation_record(sid=sid)
    rec_b = _correlation_record(sid=sid)
    await store.save_correlation(rec_a)
    await store.save_correlation(rec_b)
    page1 = await store.list_correlations(
        SessionCorrelationQuery(session_id=sid)
    )
    page2 = await store.list_correlations(
        SessionCorrelationQuery(session_id=sid)
    )
    assert [c.correlation_id for c in page1.correlations] == [
        c.correlation_id for c in page2.correlations
    ]
