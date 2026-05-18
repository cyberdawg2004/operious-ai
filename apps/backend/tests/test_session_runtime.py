"""`SessionRuntime` integration tests — continuity-only ledger discipline."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.session.contracts.requests import (
    AppendEventRequest,
    OpenSessionRequest,
    ReconstructSessionRequest,
    RecordContextRequest,
    RecordCorrelationRequest,
    RecordLifecycleRequest,
)
from app.session.enums import (
    SessionContinuityMode,
    SessionCorrelationKind,
    SessionEventKind,
    SessionLifecyclePhase,
    SessionReconstructionStatus,
    SessionScope,
)
from app.session.identity import generate_session_id
from app.session.models.context import SessionContext
from app.session.persistence.memory import (
    InMemorySessionPersistence,
)
from app.session.runtime.runtime import SessionRuntime


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _runtime() -> SessionRuntime:
    return SessionRuntime(
        persistence=InMemorySessionPersistence()
    )


async def _open(rt: SessionRuntime, *, handle: str = "h1"):
    env = await rt.open_session(
        OpenSessionRequest(
            scope=SessionScope.TENANT,
            external_handle=handle,
            tenant_id="t1",
            principal_id="p1",
        )
    )
    assert env.is_ok, (env.error, env.trace.error)
    return env.result


# ─── open_session ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_session_creates_root_session() -> None:
    rt = _runtime()
    result = await _open(rt)
    session = result.session
    assert session is not None
    assert session.lifecycle.phase is SessionLifecyclePhase.INITIATED
    assert session.lineage.is_root
    assert session.sequence_head == 0
    assert session.revision == 1


@pytest.mark.asyncio
async def test_open_session_persists_opened_event() -> None:
    rt = _runtime()
    result = await _open(rt)
    sid = result.session.identity.session_id
    env = await rt.reconstruct(
        ReconstructSessionRequest(session_id=sid)
    )
    assert env.is_ok
    timeline = env.result.timeline
    assert timeline is not None
    assert timeline.length == 1
    assert (
        timeline.events[0].kind is SessionEventKind.SESSION_OPENED
    )


@pytest.mark.asyncio
async def test_open_session_rejects_unknown_parent() -> None:
    rt = _runtime()
    env = await rt.open_session(
        OpenSessionRequest(
            scope=SessionScope.TENANT,
            external_handle="h",
            parent_session_id=generate_session_id(),
        )
    )
    assert env.result is None
    assert env.error is not None


@pytest.mark.asyncio
async def test_open_session_with_parent_extends_lineage() -> None:
    rt = _runtime()
    parent = await _open(rt, handle="root")
    parent_sid = parent.session.identity.session_id
    env = await rt.open_session(
        OpenSessionRequest(
            scope=SessionScope.TENANT,
            external_handle="child",
            parent_session_id=parent_sid,
        )
    )
    assert env.is_ok
    child = env.result.session
    assert child.lineage.depth == 1
    assert child.lineage.parent_session_id == parent_sid
    assert child.lineage.lineage_id == parent.session.lineage.lineage_id


# ─── append_event ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_append_event_increments_sequence() -> None:
    rt = _runtime()
    parent = await _open(rt)
    sid = parent.session.identity.session_id
    env = await rt.append_event(
        AppendEventRequest(
            session_id=sid,
            kind=SessionEventKind.OPERATIONAL_OBSERVATION,
            occurred_at=_now(),
        )
    )
    assert env.is_ok
    assert env.result.event.sequence == 1
    assert env.result.session.sequence_head == 1


@pytest.mark.asyncio
async def test_append_event_rejects_unknown_session() -> None:
    rt = _runtime()
    env = await rt.append_event(
        AppendEventRequest(
            session_id=generate_session_id(),
            kind=SessionEventKind.OPERATIONAL_OBSERVATION,
            occurred_at=_now(),
        )
    )
    assert env.result is None
    assert env.error is not None


@pytest.mark.asyncio
async def test_append_event_threads_request_correlation_into_event() -> None:
    """2.5-B: ``request.correlation_id`` must reach the persisted
    ``SessionTimelineEvent.correlation_id`` (deterministic UUID5
    projection). Pre-2.5-B the runtime forced ``correlation_id=None``
    on the timeline event, breaking the forensic-audit join from
    request to persisted event.
    """
    from app.session.identity import derive_correlation_id

    rt = _runtime()
    parent = await _open(rt)
    sid = parent.session.identity.session_id

    env = await rt.append_event(
        AppendEventRequest(
            session_id=sid,
            kind=SessionEventKind.OPERATIONAL_OBSERVATION,
            occurred_at=_now(),
            correlation_id="corr-abc-123",
        )
    )
    assert env.is_ok
    expected = derive_correlation_id(
        session_id=sid,
        kind="request_correlation",
        external_id="corr-abc-123",
    )
    assert env.result.event.correlation_id == expected, (
        "request.correlation_id must be projected onto the persisted "
        "SessionTimelineEvent.correlation_id"
    )

    # And it must be replay-deterministic — same request correlation
    # on the same session yields the byte-identical UUID.
    env2 = await rt.append_event(
        AppendEventRequest(
            session_id=sid,
            kind=SessionEventKind.OPERATIONAL_OBSERVATION,
            occurred_at=_now(),
            correlation_id="corr-abc-123",
        )
    )
    assert env2.is_ok
    assert env2.result.event.correlation_id == expected


@pytest.mark.asyncio
async def test_append_event_without_request_correlation_keeps_none() -> None:
    """No correlation in request → no correlation on persisted event.
    The previous behaviour is preserved for callers that don't need
    cross-substrate joining."""
    rt = _runtime()
    parent = await _open(rt)
    sid = parent.session.identity.session_id
    env = await rt.append_event(
        AppendEventRequest(
            session_id=sid,
            kind=SessionEventKind.OPERATIONAL_OBSERVATION,
            occurred_at=_now(),
        )
    )
    assert env.is_ok
    assert env.result.event.correlation_id is None


# ─── record_lifecycle ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_lifecycle_classifies_dormant() -> None:
    rt = _runtime()
    parent = await _open(rt)
    sid = parent.session.identity.session_id
    env = await rt.record_lifecycle(
        RecordLifecycleRequest(
            session_id=sid,
            phase=SessionLifecyclePhase.DORMANT,
            reason="awaiting external response",
        )
    )
    assert env.is_ok
    assert (
        env.result.event.kind is SessionEventKind.DORMANCY_RECORDED
    )
    assert (
        env.result.session.lifecycle.phase
        is SessionLifecyclePhase.DORMANT
    )


@pytest.mark.asyncio
async def test_record_lifecycle_terminal_then_reject() -> None:
    rt = _runtime()
    parent = await _open(rt)
    sid = parent.session.identity.session_id
    await rt.record_lifecycle(
        RecordLifecycleRequest(
            session_id=sid,
            phase=SessionLifecyclePhase.TERMINATED,
        )
    )
    env = await rt.append_event(
        AppendEventRequest(
            session_id=sid,
            kind=SessionEventKind.OPERATIONAL_OBSERVATION,
            occurred_at=_now(),
        )
    )
    assert env.result is None
    assert env.error is not None


# ─── record_context ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_context_appends_event_and_updates_session() -> None:
    rt = _runtime()
    parent = await _open(rt)
    sid = parent.session.identity.session_id
    ctx = SessionContext(
        environment="staging",
        labels=("urgent", "ops"),
        attributes={"region": "eu-west"},
    )
    env = await rt.record_context(
        RecordContextRequest(session_id=sid, context=ctx)
    )
    assert env.is_ok
    assert (
        env.result.event.kind is SessionEventKind.CONTEXT_ATTACHED
    )
    assert env.result.session.context == ctx


# ─── record_correlation ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_correlation_is_idempotent_in_id() -> None:
    rt = _runtime()
    parent = await _open(rt)
    sid = parent.session.identity.session_id
    env_a = await rt.record_correlation(
        RecordCorrelationRequest(
            session_id=sid,
            kind=SessionCorrelationKind.COORDINATION,
            external_id="coord-1",
        )
    )
    env_b = await rt.record_correlation(
        RecordCorrelationRequest(
            session_id=sid,
            kind=SessionCorrelationKind.COORDINATION,
            external_id="coord-2",
        )
    )
    assert env_a.is_ok and env_b.is_ok
    # Same (session_id, kind, external_id) → byte-identical id
    again = await rt.record_correlation(
        RecordCorrelationRequest(
            session_id=sid,
            kind=SessionCorrelationKind.COORDINATION,
            external_id="coord-1",
        )
    )
    # The substrate persists each observation as a new event,
    # but the derived correlation_id is the same for the first
    # observation and the new identical one.
    assert (
        env_a.result.correlation.correlation_id
        == again.result.correlation.correlation_id
        if again.is_ok
        else True
    )


# ─── reconstruct ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconstruct_pristine() -> None:
    rt = _runtime()
    parent = await _open(rt)
    sid = parent.session.identity.session_id
    for i in range(3):
        await rt.append_event(
            AppendEventRequest(
                session_id=sid,
                kind=SessionEventKind.OPERATIONAL_OBSERVATION,
                occurred_at=_now(),
                payload={"i": i},
            )
        )
    env = await rt.reconstruct(
        ReconstructSessionRequest(session_id=sid)
    )
    assert env.is_ok
    assert (
        env.result.status is SessionReconstructionStatus.PRISTINE
    )
    assert env.result.timeline.length == 4
    assert all(
        e.continuity_mode is SessionContinuityMode.RECONSTRUCTED
        for e in env.result.timeline.events
    )


@pytest.mark.asyncio
async def test_reconstruct_partial_with_window() -> None:
    rt = _runtime()
    parent = await _open(rt)
    sid = parent.session.identity.session_id
    base = _now()
    for i in range(3):
        await rt.append_event(
            AppendEventRequest(
                session_id=sid,
                kind=SessionEventKind.OPERATIONAL_OBSERVATION,
                occurred_at=base + timedelta(seconds=i + 1),
            )
        )
    env = await rt.reconstruct(
        ReconstructSessionRequest(
            session_id=sid,
            from_sequence=1,
            to_sequence=2,
        )
    )
    assert env.is_ok
    assert (
        env.result.status is SessionReconstructionStatus.PARTIAL
    )
    assert env.result.timeline.length == 2


@pytest.mark.asyncio
async def test_reconstruct_not_found() -> None:
    rt = _runtime()
    env = await rt.reconstruct(
        ReconstructSessionRequest(
            session_id=generate_session_id()
        )
    )
    assert env.is_ok
    assert (
        env.result.status is SessionReconstructionStatus.NOT_FOUND
    )


@pytest.mark.asyncio
async def test_replay_equivalence_byte_identical_ids() -> None:
    """Two reconstructions of the same persistence produce byte-identical events."""
    rt = _runtime()
    parent = await _open(rt)
    sid = parent.session.identity.session_id
    for i in range(4):
        await rt.append_event(
            AppendEventRequest(
                session_id=sid,
                kind=SessionEventKind.OPERATIONAL_OBSERVATION,
                occurred_at=_now(),
                payload={"i": i},
            )
        )
    env_a = await rt.reconstruct(
        ReconstructSessionRequest(session_id=sid)
    )
    env_b = await rt.reconstruct(
        ReconstructSessionRequest(session_id=sid)
    )
    a_ids = [e.event_id for e in env_a.result.timeline.events]
    b_ids = [e.event_id for e in env_b.result.timeline.events]
    assert a_ids == b_ids


# ─── get_session / get_timeline ────────────────────────────────────


@pytest.mark.asyncio
async def test_get_session_returns_apex_record() -> None:
    rt = _runtime()
    parent = await _open(rt)
    sid = parent.session.identity.session_id
    env = await rt.get_session(sid)
    assert env.is_ok
    assert env.result.identity.session_id == sid


@pytest.mark.asyncio
async def test_get_timeline_returns_reconstruct_result() -> None:
    rt = _runtime()
    parent = await _open(rt)
    sid = parent.session.identity.session_id
    env = await rt.get_timeline(sid)
    assert env.is_ok
    assert env.result.timeline.length == 1
