"""Operational event persistence query/page value objects."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.events.event import OperationalEvent
from app.events.identity import EventId
from app.events.substrates import OperationalSubstrate
from app.governance.capability.acts import OperationalAct


@dataclass(frozen=True, slots=True)
class OperationalEventQuery:
    event_id: EventId | None = None
    operational_act: OperationalAct | None = None
    substrate: OperationalSubstrate | None = None
    tenant_id: str | None = None
    runtime_instance_id: uuid.UUID | None = None
    root_event_id: EventId | None = None
    parent_event_id: EventId | None = None
    governance_decision_id: str | None = None
    occurred_after_or_at: datetime | None = None
    occurred_before_or_at: datetime | None = None
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("OperationalEventQuery.limit must be >= 1")
        if self.offset < 0:
            raise ValueError("OperationalEventQuery.offset must be >= 0")
        if (
            self.occurred_after_or_at is not None
            and self.occurred_before_or_at is not None
            and self.occurred_after_or_at > self.occurred_before_or_at
        ):
            raise ValueError(
                "OperationalEventQuery occurred_after_or_at must be <= "
                "occurred_before_or_at"
            )


@dataclass(frozen=True, slots=True)
class OperationalEventPage:
    events: tuple[OperationalEvent, ...]
    total: int
    limit: int = 0
    offset: int = 0


__all__ = ["OperationalEventPage", "OperationalEventQuery"]
