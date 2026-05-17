"""Timeline helpers — pure functions for building / extending timelines.

`SessionTimelineBuilder` is intentionally a pure function module
rather than a class with state. It exists so the runtime AND the
reconstruction pipeline share IDENTICAL logic for sequencing and
event-id derivation, guaranteeing replay equivalence.
"""

from app.session.timeline.builder import (
    append_event,
    build_event,
    build_timeline,
)

__all__ = ["append_event", "build_event", "build_timeline"]
