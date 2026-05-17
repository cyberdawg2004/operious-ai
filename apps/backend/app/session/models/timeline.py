"""`SessionTimeline` — append-only chronology of one session.

The timeline is an ORDERED, IMMUTABLE projection of all events
the substrate ever appended to a session. The runtime asserts:

* `events[i].sequence == i` for all `i`,
* `events[i].occurred_at <= events[i+1].occurred_at` is NOT
  required (out-of-order observations are deliberately allowed),
* `events[i].recorded_at <= events[i+1].recorded_at` IS required
  (the substrate's own arrival ordering must be monotonic).

The timeline is read-only. To extend it, the runtime constructs a
new immutable `SessionTimeline` instance with the new event
appended. The previous instance is preserved verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.session.identity import SessionId
from app.session.models.timeline_event import (
    SessionTimelineEvent,
)


@dataclass(frozen=True, slots=True)
class SessionTimeline:
    """Immutable, append-only event chronology.

    Attributes:
        session_id:      Session this timeline belongs to.
        events:          Ordered tuple of timeline events.
        head_sequence:   The sequence number of the most recent
                          event, or ``-1`` for an empty timeline.
    """

    session_id: SessionId
    events: tuple[SessionTimelineEvent, ...]
    head_sequence: int = -1

    def __post_init__(self) -> None:
        prev_sequence: int | None = None
        for index, event in enumerate(self.events):
            if event.session_id != self.session_id:
                raise ValueError(
                    f"timeline event #{index} belongs to a "
                    f"different session"
                )
            if (
                prev_sequence is not None
                and event.sequence != prev_sequence + 1
            ):
                raise ValueError(
                    f"timeline event #{index} sequence "
                    f"{event.sequence} is not contiguous with "
                    f"previous {prev_sequence}; gap or duplicate "
                    f"detected"
                )
            prev_sequence = event.sequence
        if self.events:
            expected_head = self.events[-1].sequence
        else:
            expected_head = -1
        if self.head_sequence != expected_head:
            raise ValueError(
                f"head_sequence {self.head_sequence} does not "
                f"match events tail ({expected_head})"
            )

    @property
    def is_empty(self) -> bool:
        return not self.events

    @property
    def length(self) -> int:
        return len(self.events)


__all__ = ["SessionTimeline"]
