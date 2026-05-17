"""Pure timeline construction helpers.

The runtime and the reconstruction pipeline both call into the
same helpers, guaranteeing byte-identical timelines across replays.

Three pure functions:

* `build_event(...)` — construct a single immutable timeline
                        event from a sequence number and call-site
                        fields. Event id is deterministically
                        derived from `(session_id, sequence)`.

* `append_event(timeline, event)` — return a NEW timeline with
                        `event` appended. Asserts deterministic
                        sequence ordering.

* `build_timeline(session_id, events)` — construct a timeline
                        from an unsorted iterable of events. The
                        function sorts by `sequence` and asserts
                        a contiguous monotonic chain. This is the
                        primary reconstruction entry point.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, Mapping

from app.session.enums import (
    SessionContinuityMode,
    SessionEventKind,
)
from app.session.exceptions import SessionLineageError
from app.session.identity import (
    SessionCorrelationId,
    SessionId,
    derive_event_id,
)
from app.session.models.timeline import SessionTimeline
from app.session.models.timeline_event import (
    SessionTimelineEvent,
)
from app.session.serializers.canonical import (
    canonicalize_payload,
)


def build_event(
    *,
    session_id: SessionId,
    sequence: int,
    kind: SessionEventKind,
    continuity_mode: SessionContinuityMode,
    occurred_at: datetime,
    recorded_at: datetime,
    payload: Mapping[str, Any] | None = None,
    correlation_id: SessionCorrelationId | None = None,
    annotation: str | None = None,
) -> SessionTimelineEvent:
    """Construct one immutable timeline event."""
    return SessionTimelineEvent(
        event_id=derive_event_id(
            session_id=session_id, sequence=sequence
        ),
        session_id=session_id,
        sequence=sequence,
        kind=kind,
        continuity_mode=continuity_mode,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        payload=canonicalize_payload(payload or {}),
        correlation_id=correlation_id,
        annotation=annotation,
    )


def append_event(
    timeline: SessionTimeline,
    event: SessionTimelineEvent,
) -> SessionTimeline:
    """Return a new timeline with `event` appended.

    Raises:
        SessionLineageError: if the event's session, sequence, or
            arrival ordering violates the timeline's invariants.
    """
    if event.session_id != timeline.session_id:
        raise SessionLineageError(
            "cannot append event from a different session"
        )
    expected = timeline.head_sequence + 1
    if event.sequence != expected:
        raise SessionLineageError(
            f"cannot append event sequence {event.sequence}; "
            f"expected {expected}"
        )
    if timeline.events:
        last = timeline.events[-1]
        if event.recorded_at < last.recorded_at:
            raise SessionLineageError(
                "cannot append event with recorded_at earlier "
                "than the head event"
            )
    return SessionTimeline(
        session_id=timeline.session_id,
        events=timeline.events + (event,),
        head_sequence=event.sequence,
    )


def build_timeline(
    *,
    session_id: SessionId,
    events: Iterable[SessionTimelineEvent],
) -> SessionTimeline:
    """Construct a timeline from an unsorted iterable of events.

    Sorts deterministically by `sequence` and asserts contiguous
    monotonic ordering. Raises `SessionLineageError` on gaps,
    duplicates, or session-id mismatches.
    """
    sorted_events = sorted(
        tuple(events), key=lambda e: e.sequence
    )
    prev_sequence: int | None = None
    for index, event in enumerate(sorted_events):
        if event.session_id != session_id:
            raise SessionLineageError(
                f"event #{index} belongs to a different session"
            )
        if (
            prev_sequence is not None
            and event.sequence != prev_sequence + 1
        ):
            raise SessionLineageError(
                f"event #{index} sequence {event.sequence} is "
                f"not contiguous with previous {prev_sequence}; "
                f"gap or duplicate detected"
            )
        prev_sequence = event.sequence
    head = (
        sorted_events[-1].sequence if sorted_events else -1
    )
    return SessionTimeline(
        session_id=session_id,
        events=tuple(sorted_events),
        head_sequence=head,
    )


__all__ = ["append_event", "build_event", "build_timeline"]
