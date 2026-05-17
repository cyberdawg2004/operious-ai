"""Pure-function helpers: timeline / lineage / lifecycle / serialisers."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.session.enums import (
    SessionContinuityMode,
    SessionEventKind,
    SessionLifecyclePhase,
)
from app.session.exceptions import SessionLineageError
from app.session.identity import (
    derive_event_id,
    generate_session_id,
)
from app.session.lifecycle.classifier import (
    is_terminal,
    next_phase_classification,
)
from app.session.lineage.tracker import (
    build_lineage_for_child,
    build_lineage_for_root,
)
from app.session.serializers.canonical import (
    canonicalize_payload,
    content_fingerprint,
)
from app.session.timeline.builder import (
    append_event,
    build_event,
    build_timeline,
)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ─── timeline ────────────────────────────────────────────────────────


def test_build_event_uses_deterministic_id() -> None:
    sid = generate_session_id()
    event = build_event(
        session_id=sid,
        sequence=2,
        kind=SessionEventKind.OPERATIONAL_OBSERVATION,
        continuity_mode=SessionContinuityMode.SYNCHRONOUS,
        occurred_at=_now(),
        recorded_at=_now(),
    )
    assert event.event_id == derive_event_id(
        session_id=sid, sequence=2
    )


def test_append_event_enforces_monotonic_sequence() -> None:
    sid = generate_session_id()
    e0 = build_event(
        session_id=sid,
        sequence=0,
        kind=SessionEventKind.SESSION_OPENED,
        continuity_mode=SessionContinuityMode.SYNCHRONOUS,
        occurred_at=_now(),
        recorded_at=_now(),
    )
    timeline = build_timeline(session_id=sid, events=(e0,))
    e2 = build_event(
        session_id=sid,
        sequence=2,
        kind=SessionEventKind.OPERATIONAL_OBSERVATION,
        continuity_mode=SessionContinuityMode.SYNCHRONOUS,
        occurred_at=_now(),
        recorded_at=_now(),
    )
    with pytest.raises(SessionLineageError):
        append_event(timeline, e2)


def test_build_timeline_rejects_session_mismatch() -> None:
    sid_a = generate_session_id()
    sid_b = generate_session_id()
    e = build_event(
        session_id=sid_b,
        sequence=0,
        kind=SessionEventKind.SESSION_OPENED,
        continuity_mode=SessionContinuityMode.SYNCHRONOUS,
        occurred_at=_now(),
        recorded_at=_now(),
    )
    with pytest.raises(SessionLineageError):
        build_timeline(session_id=sid_a, events=(e,))


# ─── lineage ─────────────────────────────────────────────────────────


def test_root_lineage_constructs_correctly() -> None:
    sid = generate_session_id()
    lineage = build_lineage_for_root(session_id=sid)
    assert lineage.is_root
    assert lineage.depth == 0
    assert lineage.parent_session_id is None
    assert lineage.root_session_id == sid


def test_child_lineage_appends_parent() -> None:
    parent_id = generate_session_id()
    child_id = generate_session_id()
    parent_lineage = build_lineage_for_root(
        session_id=parent_id
    )
    child_lineage = build_lineage_for_child(
        session_id=child_id, parent_lineage=parent_lineage
    )
    assert child_lineage.parent_session_id == parent_id
    assert child_lineage.depth == 1
    assert child_lineage.ancestor_session_ids == (parent_id,)
    assert child_lineage.root_session_id == parent_id
    assert child_lineage.lineage_id == parent_lineage.lineage_id


def test_child_lineage_rejects_cycle() -> None:
    parent = generate_session_id()
    parent_lineage = build_lineage_for_root(session_id=parent)
    with pytest.raises(SessionLineageError):
        build_lineage_for_child(
            session_id=parent, parent_lineage=parent_lineage
        )


# ─── lifecycle classifier ──────────────────────────────────────────


def test_terminal_phases() -> None:
    assert is_terminal(SessionLifecyclePhase.TERMINATED)
    assert is_terminal(SessionLifecyclePhase.ARCHIVED)
    assert not is_terminal(SessionLifecyclePhase.ACTIVE)


def test_next_phase_classification_dormant() -> None:
    kind = next_phase_classification(
        current=SessionLifecyclePhase.ACTIVE,
        proposed=SessionLifecyclePhase.DORMANT,
    )
    assert kind is SessionEventKind.DORMANCY_RECORDED


def test_next_phase_classification_resumption() -> None:
    kind = next_phase_classification(
        current=SessionLifecyclePhase.DORMANT,
        proposed=SessionLifecyclePhase.ACTIVE,
    )
    assert kind is SessionEventKind.RESUMPTION_RECORDED


def test_next_phase_classification_termination() -> None:
    kind = next_phase_classification(
        current=SessionLifecyclePhase.ACTIVE,
        proposed=SessionLifecyclePhase.TERMINATED,
    )
    assert kind is SessionEventKind.TERMINATION_RECORDED


def test_next_phase_classification_archival() -> None:
    kind = next_phase_classification(
        current=SessionLifecyclePhase.TERMINATED,
        proposed=SessionLifecyclePhase.ARCHIVED,
    )
    assert kind is SessionEventKind.ARCHIVAL_RECORDED


# ─── canonical serialisation ──────────────────────────────────────


def test_canonicalize_payload_sorts_keys_recursively() -> None:
    inp = {"b": {"y": 1, "x": 2}, "a": [3, {"k2": 1, "k1": 2}]}
    out = canonicalize_payload(inp)
    assert list(out.keys()) == ["a", "b"]
    assert list(out["b"].keys()) == ["x", "y"]
    assert list(out["a"][1].keys()) == ["k1", "k2"]


def test_canonicalize_handles_datetime() -> None:
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
    canonical = canonicalize_payload({"at": moment})
    assert canonical["at"] == moment.isoformat()


def test_content_fingerprint_is_byte_stable() -> None:
    a = {"a": 1, "b": [1, 2, {"x": 1, "y": 2}]}
    b = {"b": [1, 2, {"y": 2, "x": 1}], "a": 1}
    assert content_fingerprint(a) == content_fingerprint(b)


def test_content_fingerprint_changes_with_value() -> None:
    assert content_fingerprint({"a": 1}) != content_fingerprint(
        {"a": 2}
    )


def test_canonical_payload_is_json_serialisable() -> None:
    inp = {"d": datetime(2026, 1, 1, tzinfo=timezone.utc), "x": 1}
    json.dumps(canonicalize_payload(inp))
