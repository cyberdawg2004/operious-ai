"""Event chronology — monotonic ordering primitive (P2-D).

A constitutionally meaningful event must answer "at what chronology
point?". The answer is the pair (runtime_instance_id, sequence)
which is globally unique and totally ordered within the originating
runtime. The wall-clock ``occurred_at`` is **advisory only** —
subject to clock skew, NTP adjustments, and replay-time
reconstruction. Sequence is authoritative.

Why a typed pair instead of a single timestamp:

* Clocks lie. Two events emitted in the same microsecond by the same
  runtime would collide under a timestamp-only model. The
  (instance, sequence) pair is collision-free by construction.
* Replay determinism. A replayed event must reproduce the same
  ``EventChronology`` for the same emission point; wall-clock can be
  re-stamped, sequence cannot.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.events.exceptions import EventChronologyError


@dataclass(frozen=True, slots=True)
class EventChronology:
    """Monotonic ordering of one :class:`OperationalEvent`.

    Attributes:
        runtime_instance_id: Identifier of the runtime instance that
            emitted the event. Stable for the lifetime of the
            process.
        sequence: Monotonic counter within ``runtime_instance_id``.
            Must be >= 0. The first event a runtime emits has
            sequence=0.
        occurred_at: Wall-clock timestamp (advisory only; sequence is
            authoritative for ordering).
    """

    runtime_instance_id: uuid.UUID
    sequence: int
    occurred_at: datetime

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise EventChronologyError(
                "EventChronology.sequence must be >= 0; got "
                f"{self.sequence!r}"
            )


__all__ = ["EventChronology"]
