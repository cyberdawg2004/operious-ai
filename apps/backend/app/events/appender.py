"""Narrow appender wrapper for request-boundary event emission."""

from __future__ import annotations

from app.events.event import OperationalEvent
from app.events.identity import EventId
from app.events.persistence import OperationalEventPersistenceProtocol
from app.events.runtime import OperationalEventAppendResult, OperationalEventRuntime


class OperationalEventAppender:
    """Append-only facade over the canonical event runtime."""

    def __init__(
        self,
        *,
        persistence: OperationalEventPersistenceProtocol,
    ) -> None:
        self._runtime = OperationalEventRuntime(persistence=persistence)

    async def append_event(
        self,
        event: OperationalEvent,
        *,
        expected_tenant_id: str | None = None,
    ) -> OperationalEventAppendResult:
        return await self._runtime.append_event(
            event,
            expected_tenant_id=expected_tenant_id,
        )

    async def get_event(
        self,
        event_id: EventId,
        *,
        expected_tenant_id: str | None = None,
    ) -> OperationalEvent | None:
        return await self._runtime.get_event(
            event_id,
            expected_tenant_id=expected_tenant_id,
        )


__all__ = ["OperationalEventAppender"]
