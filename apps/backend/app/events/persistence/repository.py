"""Storage-agnostic operational event persistence contract."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.events.event import OperationalEvent
from app.events.identity import EventId
from app.events.persistence.models import (
    OperationalEventPage,
    OperationalEventQuery,
)


@runtime_checkable
class OperationalEventPersistenceProtocol(Protocol):
    """Durable append-only store for canonical operational events."""

    async def append_event(
        self,
        event: OperationalEvent,
    ) -> OperationalEvent: ...

    async def get_event(
        self,
        event_id: EventId,
        *,
        expected_tenant_id: str | None = None,
    ) -> OperationalEvent | None: ...

    async def list_events(
        self,
        query: OperationalEventQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> OperationalEventPage: ...


__all__ = ["OperationalEventPersistenceProtocol"]
