"""Deterministic operational event ordering helpers.

Wall-clock timestamps are advisory in the event fabric. Replay reads
therefore order by persisted causal and monotonic chronology axes
instead of by ``occurred_at``.
"""

from __future__ import annotations

from app.events.event import OperationalEvent


def operational_event_replay_sort_key(
    event: OperationalEvent,
) -> tuple[str, int, str, int, str]:
    """Canonical deterministic ordering for replay/read views."""

    return (
        str(event.causality.root_event_id),
        event.causality.depth,
        str(event.chronology.runtime_instance_id),
        event.chronology.sequence,
        str(event.event_id),
    )


__all__ = ["operational_event_replay_sort_key"]
