"""OperationalEventRuntime — canonical event fabric authority."""

from __future__ import annotations

from dataclasses import dataclass

from app.events.event import OperationalEvent
from app.events.exceptions import EventCausalityError
from app.events.identity import EventId
from app.events.persistence import (
    OperationalEventPage,
    OperationalEventPersistenceProtocol,
    OperationalEventQuery,
)


@dataclass(frozen=True, slots=True)
class OperationalEventAppendResult:
    """Result of appending a canonical operational event."""

    event: OperationalEvent


class OperationalEventRuntime:
    """Apex append/read authority for canonical operational events.

    Phase 2-A deliberately does not emit events from other substrates.
    It closes the durable authority boundary first; later Phase 2
    slices can adopt this runtime without inventing parallel
    chronology systems.
    """

    def __init__(
        self,
        *,
        persistence: OperationalEventPersistenceProtocol,
    ) -> None:
        self._persistence = persistence

    async def append_event(
        self,
        event: OperationalEvent,
        *,
        expected_tenant_id: str | None = None,
    ) -> OperationalEventAppendResult:
        """Append one immutable event through canonical event authority."""

        _validate_optional_tenant_id(expected_tenant_id)
        _validate_event_causality(event)
        if expected_tenant_id is not None and event.tenant_id != expected_tenant_id:
            raise EventCausalityError(
                "event tenant_id does not match expected_tenant_id"
            )
        persisted = await self._persistence.append_event(event)
        return OperationalEventAppendResult(event=persisted)

    async def get_event(
        self,
        event_id: EventId,
        *,
        expected_tenant_id: str | None = None,
    ) -> OperationalEvent | None:
        """Read one event through event authority."""

        _validate_optional_tenant_id(expected_tenant_id)
        return await self._persistence.get_event(
            event_id,
            expected_tenant_id=expected_tenant_id,
        )

    async def list_events(
        self,
        query: OperationalEventQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> OperationalEventPage:
        """List canonical events through event authority."""

        _validate_optional_tenant_id(expected_tenant_id)
        return await self._persistence.list_events(
            query,
            expected_tenant_id=expected_tenant_id,
        )


def _validate_optional_tenant_id(tenant_id: str | None) -> None:
    if tenant_id is not None and not tenant_id:
        raise ValueError("expected_tenant_id must be non-empty when supplied")


def _validate_event_causality(event: OperationalEvent) -> None:
    if event.causality.is_root and event.causality.root_event_id != event.event_id:
        raise EventCausalityError(
            "root event must have causality.root_event_id equal to event_id"
        )
    if event.causality.parent_event_id == event.event_id:
        raise EventCausalityError("event cannot name itself as parent")


__all__ = ["OperationalEventAppendResult", "OperationalEventRuntime"]
