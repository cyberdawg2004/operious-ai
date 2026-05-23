"""Postgres operational event fabric persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError

from app.events.causality import EventCausality
from app.events.chronology import EventChronology
from app.events.db.models import OperationalEventRow
from app.events.event import OperationalEvent
from app.events.exceptions import EventPersistenceError
from app.events.identity import EventId
from app.events.persistence.models import (
    OperationalEventPage,
    OperationalEventQuery,
)
from app.events.persistence.repository import (
    OperationalEventPersistenceProtocol,
)
from app.events.substrates import OperationalSubstrate
from app.governance.capability.acts import OperationalAct
from app.governance.enums import Decision
from app.repositories.base import BaseRepository

_SERVER_PAGE_HARD_CAP = 500


class PostgresOperationalEventPersistence(
    BaseRepository, OperationalEventPersistenceProtocol
):
    """Append-only Postgres authority for canonical events."""

    async def append_event(
        self,
        event: OperationalEvent,
    ) -> OperationalEvent:
        row = _event_to_row(event)
        try:
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError as exc:
            existing = await self.get_event(event.event_id)
            if existing is not None:
                if existing == event:
                    return existing
                raise EventPersistenceError(
                    f"event {event.event_id!r} already exists with different content"
                ) from exc
            chronology_owner = await self._get_event_by_chronology(
                runtime_instance_id=event.chronology.runtime_instance_id,
                sequence=event.chronology.sequence,
            )
            if chronology_owner is not None:
                raise EventPersistenceError(
                    "chronology point already has an event: "
                    f"runtime_instance_id={event.chronology.runtime_instance_id!s}, "
                    f"sequence={event.chronology.sequence!r}, "
                    f"event_id={chronology_owner.event_id!r}"
                ) from exc
            raise EventPersistenceError(
                f"event {event.event_id!r} could not be appended"
            ) from exc
        return event

    async def get_event(
        self,
        event_id: EventId,
        *,
        expected_tenant_id: str | None = None,
    ) -> OperationalEvent | None:
        stmt = select(OperationalEventRow).where(
            OperationalEventRow.event_id == uuid.UUID(str(event_id))
        )
        if expected_tenant_id is not None:
            stmt = stmt.where(OperationalEventRow.tenant_id == expected_tenant_id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_event(row)

    async def list_events(
        self,
        query: OperationalEventQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> OperationalEventPage:
        stmt = select(OperationalEventRow)
        stmt = _apply_filters(
            stmt,
            query=query,
            expected_tenant_id=expected_tenant_id,
        )
        stmt = stmt.order_by(
            OperationalEventRow.occurred_at,
            OperationalEventRow.runtime_instance_id,
            OperationalEventRow.sequence,
            OperationalEventRow.event_id,
        )
        limit = _bounded_limit(query.limit)
        total = int(
            (
                await self.session.execute(
                    select(func.count()).select_from(
                        stmt.order_by(None).subquery()
                    )
                )
            ).scalar_one()
        )
        rows = tuple(
            (
                await self.session.execute(
                    stmt.offset(query.offset).limit(limit)
                )
            ).scalars()
        )
        return OperationalEventPage(
            events=tuple(_row_to_event(row) for row in rows),
            total=total,
            limit=limit,
            offset=query.offset,
        )

    async def _get_event_by_chronology(
        self,
        *,
        runtime_instance_id: uuid.UUID,
        sequence: int,
    ) -> OperationalEvent | None:
        stmt = select(OperationalEventRow).where(
            OperationalEventRow.runtime_instance_id == runtime_instance_id,
            OperationalEventRow.sequence == sequence,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_event(row)


def _apply_filters(
    stmt: Select[tuple[OperationalEventRow]],
    *,
    query: OperationalEventQuery,
    expected_tenant_id: str | None,
) -> Select[tuple[OperationalEventRow]]:
    if expected_tenant_id is not None:
        stmt = stmt.where(OperationalEventRow.tenant_id == expected_tenant_id)
    if query.event_id is not None:
        stmt = stmt.where(
            OperationalEventRow.event_id == uuid.UUID(str(query.event_id))
        )
    if query.operational_act is not None:
        stmt = stmt.where(
            OperationalEventRow.operational_act == query.operational_act.value
        )
    if query.substrate is not None:
        stmt = stmt.where(OperationalEventRow.substrate == query.substrate.value)
    if query.tenant_id is not None:
        stmt = stmt.where(OperationalEventRow.tenant_id == query.tenant_id)
    if query.runtime_instance_id is not None:
        stmt = stmt.where(
            OperationalEventRow.runtime_instance_id == query.runtime_instance_id
        )
    if query.root_event_id is not None:
        stmt = stmt.where(
            OperationalEventRow.root_event_id == uuid.UUID(str(query.root_event_id))
        )
    if query.parent_event_id is not None:
        stmt = stmt.where(
            OperationalEventRow.parent_event_id
            == uuid.UUID(str(query.parent_event_id))
        )
    if query.governance_decision_id is not None:
        stmt = stmt.where(
            OperationalEventRow.governance_decision_id
            == query.governance_decision_id
        )
    if query.occurred_after_or_at is not None:
        stmt = stmt.where(
            OperationalEventRow.occurred_at >= query.occurred_after_or_at
        )
    if query.occurred_before_or_at is not None:
        stmt = stmt.where(
            OperationalEventRow.occurred_at <= query.occurred_before_or_at
        )
    return stmt


def _bounded_limit(limit: int) -> int:
    if limit > _SERVER_PAGE_HARD_CAP:
        raise ValueError(f"limit must be <= {_SERVER_PAGE_HARD_CAP}")
    return limit


def _event_to_row(event: OperationalEvent) -> OperationalEventRow:
    return OperationalEventRow(
        event_id=uuid.UUID(str(event.event_id)),
        operational_act=event.operational_act.value,
        substrate=event.substrate.value,
        root_event_id=uuid.UUID(str(event.causality.root_event_id)),
        parent_event_id=(
            None
            if event.causality.parent_event_id is None
            else uuid.UUID(str(event.causality.parent_event_id))
        ),
        causality_depth=event.causality.depth,
        runtime_instance_id=event.chronology.runtime_instance_id,
        sequence=event.chronology.sequence,
        occurred_at=event.chronology.occurred_at,
        tenant_id=event.tenant_id,
        principal_id=event.principal_id,
        organization_id=event.organization_id,
        environment_id=event.environment_id,
        tenant_authority_source=event.tenant_authority_source,
        governance_decision=(
            None
            if event.governance_decision is None
            else event.governance_decision.value
        ),
        governance_decision_id=event.governance_decision_id,
        metadata_json=dict(event.metadata),
    )


def _row_to_event(row: OperationalEventRow) -> OperationalEvent:
    return OperationalEvent(
        event_id=EventId(str(row.event_id)),
        operational_act=OperationalAct(row.operational_act),
        substrate=OperationalSubstrate(row.substrate),
        causality=EventCausality(
            root_event_id=EventId(str(row.root_event_id)),
            parent_event_id=(
                None
                if row.parent_event_id is None
                else EventId(str(row.parent_event_id))
            ),
            depth=row.causality_depth,
        ),
        chronology=EventChronology(
            runtime_instance_id=row.runtime_instance_id,
            sequence=row.sequence,
            occurred_at=row.occurred_at,
        ),
        tenant_id=row.tenant_id,
        principal_id=row.principal_id,
        organization_id=row.organization_id,
        environment_id=row.environment_id,
        tenant_authority_source=row.tenant_authority_source,
        governance_decision=(
            None
            if row.governance_decision is None
            else Decision(row.governance_decision)
        ),
        governance_decision_id=row.governance_decision_id,
        metadata=dict(row.metadata_json),
    )


__all__ = ["PostgresOperationalEventPersistence"]
