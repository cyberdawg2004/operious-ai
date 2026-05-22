"""In-memory operational event persistence."""

from __future__ import annotations

from app.events.event import OperationalEvent
from app.events.identity import EventId
from app.events.exceptions import EventPersistenceError
from app.events.persistence.models import (
    OperationalEventPage,
    OperationalEventQuery,
)
from app.events.persistence.repository import (
    OperationalEventPersistenceProtocol,
)


class InMemoryOperationalEventPersistence(OperationalEventPersistenceProtocol):
    """Reference append-only event fabric store."""

    def __init__(self) -> None:
        self._events: dict[EventId, OperationalEvent] = {}
        self._chronology_index: dict[tuple[str, int], EventId] = {}

    async def append_event(
        self,
        event: OperationalEvent,
    ) -> OperationalEvent:
        existing = self._events.get(event.event_id)
        if existing is not None:
            if existing == event:
                return existing
            raise EventPersistenceError(
                f"event {event.event_id!r} already exists with different content"
            )
        chronology_key = (
            str(event.chronology.runtime_instance_id),
            event.chronology.sequence,
        )
        existing_event_id = self._chronology_index.get(chronology_key)
        if existing_event_id is not None:
            raise EventPersistenceError(
                "chronology point already has an event: "
                f"runtime_instance_id={chronology_key[0]!r}, "
                f"sequence={chronology_key[1]!r}, "
                f"event_id={existing_event_id!r}"
            )
        self._events[event.event_id] = event
        self._chronology_index[chronology_key] = event.event_id
        return event

    async def get_event(
        self,
        event_id: EventId,
        *,
        expected_tenant_id: str | None = None,
    ) -> OperationalEvent | None:
        event = self._events.get(event_id)
        if event is None:
            return None
        if expected_tenant_id is not None and event.tenant_id != expected_tenant_id:
            return None
        return event

    async def list_events(
        self,
        query: OperationalEventQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> OperationalEventPage:
        events = [
            event
            for event in self._events.values()
            if _matches_event(
                event,
                query=query,
                expected_tenant_id=expected_tenant_id,
            )
        ]
        events.sort(
            key=lambda event: (
                event.chronology.occurred_at,
                str(event.chronology.runtime_instance_id),
                event.chronology.sequence,
                str(event.event_id),
            )
        )
        total = len(events)
        sliced = events[query.offset : query.offset + query.limit]
        return OperationalEventPage(
            events=tuple(sliced),
            total=total,
            offset=query.offset,
        )


def _matches_event(
    event: OperationalEvent,
    *,
    query: OperationalEventQuery,
    expected_tenant_id: str | None,
) -> bool:
    if expected_tenant_id is not None and event.tenant_id != expected_tenant_id:
        return False
    if query.event_id is not None and event.event_id != query.event_id:
        return False
    if (
        query.operational_act is not None
        and event.operational_act is not query.operational_act
    ):
        return False
    if query.substrate is not None and event.substrate is not query.substrate:
        return False
    if query.tenant_id is not None and event.tenant_id != query.tenant_id:
        return False
    if (
        query.runtime_instance_id is not None
        and event.chronology.runtime_instance_id != query.runtime_instance_id
    ):
        return False
    if (
        query.root_event_id is not None
        and event.causality.root_event_id != query.root_event_id
    ):
        return False
    if (
        query.parent_event_id is not None
        and event.causality.parent_event_id != query.parent_event_id
    ):
        return False
    if (
        query.governance_decision_id is not None
        and event.governance_decision_id != query.governance_decision_id
    ):
        return False
    if (
        query.occurred_after_or_at is not None
        and event.chronology.occurred_at < query.occurred_after_or_at
    ):
        return False
    if (
        query.occurred_before_or_at is not None
        and event.chronology.occurred_at > query.occurred_before_or_at
    ):
        return False
    return True


__all__ = ["InMemoryOperationalEventPersistence"]
