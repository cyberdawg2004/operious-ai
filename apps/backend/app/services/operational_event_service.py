"""Operational event application service boundary."""

from __future__ import annotations

from datetime import datetime

from app.events import (
    EventId,
    OperationalEventPage,
    OperationalEventQuery,
    OperationalReplayTrace,
    OperationalSubstrate,
)
from app.events.read_service import OperationalEventReader
from app.governance.capability.acts import OperationalAct


class OperationalEventService:
    """Command Center service for canonical event-fabric reads."""

    def __init__(self, *, reader: OperationalEventReader) -> None:
        self._reader = reader

    async def list_events(
        self,
        *,
        tenant_id: str,
        event_id: str | None = None,
        operational_act: str | None = None,
        substrate: str | None = None,
        root_event_id: str | None = None,
        parent_event_id: str | None = None,
        governance_decision_id: str | None = None,
        occurred_after_or_at: datetime | None = None,
        occurred_before_or_at: datetime | None = None,
        limit: int,
        offset: int,
    ) -> OperationalEventPage:
        return await self._reader.list_events(
            _query(
                event_id=event_id,
                operational_act=operational_act,
                substrate=substrate,
                root_event_id=root_event_id,
                parent_event_id=parent_event_id,
                governance_decision_id=governance_decision_id,
                occurred_after_or_at=occurred_after_or_at,
                occurred_before_or_at=occurred_before_or_at,
                limit=limit,
                offset=offset,
            ),
            expected_tenant_id=tenant_id,
        )

    async def load_replay_trace(
        self,
        *,
        tenant_id: str,
        event_id: str | None = None,
        root_event_id: str | None = None,
        operational_act: str | None = None,
        substrate: str | None = None,
        governance_decision_id: str | None = None,
        occurred_after_or_at: datetime | None = None,
        occurred_before_or_at: datetime | None = None,
        limit: int,
        offset: int,
    ) -> OperationalReplayTrace:
        return await self._reader.load_replay_trace(
            event_id=EventId(event_id) if event_id is not None else None,
            root_event_id=(
                EventId(root_event_id) if root_event_id is not None else None
            ),
            query=_query(
                event_id=None,
                operational_act=operational_act,
                substrate=substrate,
                root_event_id=root_event_id,
                parent_event_id=None,
                governance_decision_id=governance_decision_id,
                occurred_after_or_at=occurred_after_or_at,
                occurred_before_or_at=occurred_before_or_at,
                limit=limit,
                offset=offset,
            ),
            expected_tenant_id=tenant_id,
        )


def _query(
    *,
    event_id: str | None,
    operational_act: str | None,
    substrate: str | None,
    root_event_id: str | None,
    parent_event_id: str | None,
    governance_decision_id: str | None,
    occurred_after_or_at: datetime | None,
    occurred_before_or_at: datetime | None,
    limit: int,
    offset: int,
) -> OperationalEventQuery:
    return OperationalEventQuery(
        event_id=EventId(event_id) if event_id is not None else None,
        operational_act=(
            OperationalAct(operational_act)
            if operational_act is not None
            else None
        ),
        substrate=(
            OperationalSubstrate(substrate) if substrate is not None else None
        ),
        root_event_id=(
            EventId(root_event_id) if root_event_id is not None else None
        ),
        parent_event_id=(
            EventId(parent_event_id) if parent_event_id is not None else None
        ),
        governance_decision_id=governance_decision_id,
        occurred_after_or_at=occurred_after_or_at,
        occurred_before_or_at=occurred_before_or_at,
        limit=limit,
        offset=offset,
    )


__all__ = ["OperationalEventService"]
