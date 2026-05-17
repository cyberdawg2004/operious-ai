"""Frozen-shape + invariant tests for session value objects."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from app.session.enums import (
    SessionContinuityMode,
    SessionEventKind,
    SessionLifecyclePhase,
    SessionScope,
)
from app.session.identity import (
    derive_event_id,
    derive_lineage_id,
    generate_session_id,
)
from app.session.models.context import SessionContext
from app.session.models.identity import SessionIdentity
from app.session.models.lifecycle import SessionLifecycle
from app.session.models.lineage import SessionLineage
from app.session.models.session import OperationalSession
from app.session.models.timeline import SessionTimeline
from app.session.models.timeline_event import (
    SessionTimelineEvent,
)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def test_session_identity_rejects_empty_handle() -> None:
    with pytest.raises(ValueError):
        SessionIdentity(
            session_id=generate_session_id(),
            scope=SessionScope.TENANT,
            external_handle="",
        )


def test_session_identity_is_frozen() -> None:
    sid = SessionIdentity(
        session_id=generate_session_id(),
        scope=SessionScope.TENANT,
        external_handle="x",
    )
    with pytest.raises(FrozenInstanceError):
        sid.external_handle = "mut"  # type: ignore[misc]


def test_session_lineage_root_invariant() -> None:
    sid = generate_session_id()
    SessionLineage(
        lineage_id=derive_lineage_id(root_session_id=sid),
        session_id=sid,
        root_session_id=sid,
        parent_session_id=None,
        ancestor_session_ids=(),
        depth=0,
    )


def test_session_lineage_rejects_self_ancestor() -> None:
    sid = generate_session_id()
    with pytest.raises(ValueError):
        SessionLineage(
            lineage_id=derive_lineage_id(root_session_id=sid),
            session_id=sid,
            root_session_id=sid,
            parent_session_id=sid,
            ancestor_session_ids=(sid,),
            depth=1,
        )


def test_session_lineage_depth_must_match_chain() -> None:
    parent = generate_session_id()
    child = generate_session_id()
    with pytest.raises(ValueError):
        SessionLineage(
            lineage_id=derive_lineage_id(root_session_id=parent),
            session_id=child,
            root_session_id=parent,
            parent_session_id=parent,
            ancestor_session_ids=(parent,),
            depth=99,
        )


def test_session_lineage_rejects_root_with_parent_mismatch() -> None:
    sid = generate_session_id()
    other = generate_session_id()
    with pytest.raises(ValueError):
        SessionLineage(
            lineage_id=derive_lineage_id(root_session_id=other),
            session_id=sid,
            root_session_id=other,
            parent_session_id=None,
            ancestor_session_ids=(),
            depth=0,
        )


def test_timeline_event_requires_tz_aware_datetimes() -> None:
    sid = generate_session_id()
    with pytest.raises(ValueError):
        SessionTimelineEvent(
            event_id=derive_event_id(session_id=sid, sequence=0),
            session_id=sid,
            sequence=0,
            kind=SessionEventKind.SESSION_OPENED,
            continuity_mode=SessionContinuityMode.SYNCHRONOUS,
            occurred_at=datetime(2026, 1, 1),  # naive!
            recorded_at=_now(),
        )


def test_timeline_rejects_session_id_mismatch() -> None:
    sid_a = generate_session_id()
    sid_b = generate_session_id()
    event = SessionTimelineEvent(
        event_id=derive_event_id(session_id=sid_b, sequence=0),
        session_id=sid_b,
        sequence=0,
        kind=SessionEventKind.SESSION_OPENED,
        continuity_mode=SessionContinuityMode.SYNCHRONOUS,
        occurred_at=_now(),
        recorded_at=_now(),
    )
    with pytest.raises(ValueError):
        SessionTimeline(
            session_id=sid_a, events=(event,), head_sequence=0
        )


def test_timeline_rejects_sequence_gap() -> None:
    sid = generate_session_id()
    e0 = SessionTimelineEvent(
        event_id=derive_event_id(session_id=sid, sequence=0),
        session_id=sid,
        sequence=0,
        kind=SessionEventKind.SESSION_OPENED,
        continuity_mode=SessionContinuityMode.SYNCHRONOUS,
        occurred_at=_now(),
        recorded_at=_now(),
    )
    e2 = SessionTimelineEvent(
        event_id=derive_event_id(session_id=sid, sequence=2),
        session_id=sid,
        sequence=2,
        kind=SessionEventKind.OPERATIONAL_OBSERVATION,
        continuity_mode=SessionContinuityMode.SYNCHRONOUS,
        occurred_at=_now(),
        recorded_at=_now(),
    )
    with pytest.raises(ValueError):
        SessionTimeline(
            session_id=sid, events=(e0, e2), head_sequence=2
        )


def test_timeline_accepts_windowed_subrange() -> None:
    """Windowed reconstructions don't have to start at sequence 0."""
    sid = generate_session_id()
    e1 = SessionTimelineEvent(
        event_id=derive_event_id(session_id=sid, sequence=1),
        session_id=sid,
        sequence=1,
        kind=SessionEventKind.OPERATIONAL_OBSERVATION,
        continuity_mode=SessionContinuityMode.RECONSTRUCTED,
        occurred_at=_now(),
        recorded_at=_now(),
    )
    e2 = SessionTimelineEvent(
        event_id=derive_event_id(session_id=sid, sequence=2),
        session_id=sid,
        sequence=2,
        kind=SessionEventKind.OPERATIONAL_OBSERVATION,
        continuity_mode=SessionContinuityMode.RECONSTRUCTED,
        occurred_at=_now(),
        recorded_at=_now(),
    )
    timeline = SessionTimeline(
        session_id=sid, events=(e1, e2), head_sequence=2
    )
    assert timeline.length == 2
    assert timeline.head_sequence == 2


def test_session_context_rejects_callable_attribute() -> None:
    with pytest.raises(ValueError):
        SessionContext(attributes={"f": lambda: None})


def test_operational_session_requires_tz_aware_opened_at() -> None:
    sid = generate_session_id()
    identity = SessionIdentity(
        session_id=sid,
        scope=SessionScope.TENANT,
        external_handle="x",
    )
    lineage = SessionLineage(
        lineage_id=derive_lineage_id(root_session_id=sid),
        session_id=sid,
        root_session_id=sid,
        parent_session_id=None,
        ancestor_session_ids=(),
        depth=0,
    )
    with pytest.raises(ValueError):
        OperationalSession(
            identity=identity,
            opened_at=datetime(2026, 1, 1),  # naive
            lifecycle=SessionLifecycle(
                phase=SessionLifecyclePhase.INITIATED,
                recorded_at=_now(),
            ),
            lineage=lineage,
        )


def test_operational_session_lineage_session_id_must_match() -> None:
    sid = generate_session_id()
    other = generate_session_id()
    identity = SessionIdentity(
        session_id=sid,
        scope=SessionScope.TENANT,
        external_handle="x",
    )
    bad_lineage = SessionLineage(
        lineage_id=derive_lineage_id(root_session_id=other),
        session_id=other,
        root_session_id=other,
        parent_session_id=None,
        ancestor_session_ids=(),
        depth=0,
    )
    with pytest.raises(ValueError):
        OperationalSession(
            identity=identity,
            opened_at=_now(),
            lifecycle=SessionLifecycle(
                phase=SessionLifecyclePhase.INITIATED,
                recorded_at=_now(),
            ),
            lineage=bad_lineage,
        )


def test_models_are_slotted_no_dict() -> None:
    sid = generate_session_id()
    obj = SessionIdentity(
        session_id=sid,
        scope=SessionScope.TENANT,
        external_handle="x",
    )
    with pytest.raises(AttributeError):
        obj.__dict__  # noqa: B018
