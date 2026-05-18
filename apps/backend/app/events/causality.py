"""Event causality — parent + root + depth (P2-D).

A constitutionally meaningful event must answer "because of what
parent causality?". Causality is encoded as a typed envelope rather
than a free-form parent pointer so that downstream consumers
(supervisor, replay, audit) can reconstruct the operational chain
without re-deriving it from metadata.

Root vs child:

* A **root event** is the genesis of a causal chain. It satisfies
  ``parent_event_id is None`` AND ``depth == 0``. Its
  ``root_event_id`` equals the event's own ``event_id``.
* A **child event** has both ``parent_event_id`` non-None AND
  ``depth >= 1``. Its ``root_event_id`` is the genesis of the chain.

Mismatches raise :class:`EventCausalityError` at construction.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.events.exceptions import EventCausalityError
from app.events.identity import EventId


@dataclass(frozen=True, slots=True)
class EventCausality:
    """Causality envelope for one :class:`OperationalEvent`.

    Attributes:
        root_event_id: First event in the causal chain (genesis).
            For a root event this equals the event's own
            ``event_id``.
        parent_event_id: Immediate predecessor. ``None`` for a root
            event.
        depth: Distance from the root. 0 for a root event; >=1 for a
            child event.
    """

    root_event_id: EventId
    parent_event_id: EventId | None = None
    depth: int = 0

    def __post_init__(self) -> None:
        if self.depth < 0:
            raise EventCausalityError(
                "EventCausality.depth must be >= 0; got "
                f"{self.depth!r}"
            )
        if self.parent_event_id is None and self.depth != 0:
            raise EventCausalityError(
                "root EventCausality (parent_event_id=None) must "
                f"have depth=0; got depth={self.depth!r}"
            )
        if self.parent_event_id is not None and self.depth == 0:
            raise EventCausalityError(
                "non-root EventCausality (parent_event_id set) must "
                "have depth>=1; got depth=0"
            )

    @property
    def is_root(self) -> bool:
        return self.parent_event_id is None


__all__ = ["EventCausality"]
