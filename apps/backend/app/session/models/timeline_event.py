"""`SessionTimelineEvent` — atomic, immutable, append-only timeline entry.

Every event the substrate ever records is one of these. The event
classification (`SessionEventKind`) tags the semantic meaning;
the canonical `payload` mapping carries the event-specific
audit fields.

Determinism invariants:

* `sequence` is monotonic per session (the runtime asserts
  strictly increasing).
* `event_id` is deterministically derivable from
  `(session_id, sequence)` so a reconstructed timeline produces
  byte-identical event ids.
* `occurred_at` and `recorded_at` are both timezone-aware UTC
  datetimes; reconstruction preserves them verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.session.enums import (
    SessionContinuityMode,
    SessionEventKind,
)
from app.session.identity import (
    SessionCorrelationId,
    SessionEventId,
    SessionId,
)


@dataclass(frozen=True, slots=True)
class SessionTimelineEvent:
    """One immutable timeline event.

    Attributes:
        event_id:        Deterministic event identifier.
        session_id:      The session this event belongs to.
        sequence:        Monotonic per-session sequence number,
                          starting at 0 for the SESSION_OPENED
                          event.
        kind:            Classification of the event.
        continuity_mode: How the event entered the timeline
                          (SYNCHRONOUS / DEFERRED / RECONSTRUCTED).
        occurred_at:     Wall-clock timestamp of the underlying
                          observation.
        recorded_at:     Wall-clock timestamp of the substrate
                          append.
        payload:         Canonical, JSON-serialisable mapping of
                          event-specific audit fields. The
                          substrate never interprets this — it is
                          replay material only.
        correlation_id:  Optional cross-substrate correlation
                          handle linking this event to a
                          `SessionCorrelation`.
        annotation:      Free-form human-readable note.
        idempotency_key: Optional replay-stable key. Duplicate
                          appends with the same key return the
                          original event instead of advancing
                          chronology.
    """

    event_id: SessionEventId
    session_id: SessionId
    sequence: int
    kind: SessionEventKind
    continuity_mode: SessionContinuityMode
    occurred_at: datetime
    recorded_at: datetime
    payload: Mapping[str, Any] = field(default_factory=dict)
    correlation_id: SessionCorrelationId | None = None
    annotation: str | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError(
                "SessionTimelineEvent.sequence must be non-negative"
            )
        if self.occurred_at.tzinfo is None:
            raise ValueError(
                "SessionTimelineEvent.occurred_at must be "
                "timezone-aware (UTC)"
            )
        if self.recorded_at.tzinfo is None:
            raise ValueError(
                "SessionTimelineEvent.recorded_at must be "
                "timezone-aware (UTC)"
            )
        if self.idempotency_key is not None and not self.idempotency_key:
            raise ValueError(
                "SessionTimelineEvent.idempotency_key must be non-empty"
            )


__all__ = ["SessionTimelineEvent"]
