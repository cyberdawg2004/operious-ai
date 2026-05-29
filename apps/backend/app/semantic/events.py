"""Append-only semantic circuit event repository."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.dialects import postgresql, sqlite

from app.repositories.base import BaseRepository
from app.semantic.db.models import SemanticCircuitEventRow

_EVENT_STATES = frozenset({"CLOSED", "TRIPPED", "RESET"})


@dataclass(frozen=True)
class SemanticCircuitEventRecord:
    event_id: str
    tenant_id: str
    channel: str
    state: str
    trigger_ticket_id: str | None
    cluster_size: int | None
    similarity_threshold: float | None
    window_seconds: int | None
    occurred_at: datetime
    metadata: dict[str, Any]


class SemanticCircuitEventRepository(BaseRepository):
    """INSERT-only repository for semantic circuit audit events."""

    async def write(self, record: SemanticCircuitEventRecord) -> None:
        _assert_tenant(record.tenant_id, record.tenant_id)
        if record.state not in _EVENT_STATES:
            raise ValueError("unsupported semantic circuit state")
        values = _record_values(record)
        dialect_name = self.session.get_bind().dialect.name
        if dialect_name == "sqlite":
            statement = (
                sqlite.insert(SemanticCircuitEventRow)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["event_id"])
            )
        else:
            statement = (
                postgresql.insert(SemanticCircuitEventRow)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["event_id"])
            )
        await self.session.execute(statement)

    async def list_for_tenant(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        channel: str | None = None,
        limit: int = 50,
    ) -> list[SemanticCircuitEventRecord]:
        _assert_tenant(tenant_id, expected_tenant_id)
        bounded_limit = max(1, min(limit, 500))
        statement: Select[tuple[SemanticCircuitEventRow]] = select(
            SemanticCircuitEventRow
        ).where(SemanticCircuitEventRow.tenant_id == tenant_id)
        if channel is not None:
            statement = statement.where(SemanticCircuitEventRow.channel == channel)
        rows = (
            await self.session.scalars(
                statement.order_by(SemanticCircuitEventRow.occurred_at.desc()).limit(
                    bounded_limit
                )
            )
        ).all()
        return [_record_from_row(row) for row in rows]


def _record_values(record: SemanticCircuitEventRecord) -> Mapping[str, Any]:
    return {
        "event_id": uuid.UUID(record.event_id),
        "tenant_id": record.tenant_id,
        "channel": record.channel,
        "state": record.state,
        "trigger_ticket_id": (
            uuid.UUID(record.trigger_ticket_id)
            if record.trigger_ticket_id is not None
            else None
        ),
        "cluster_size": record.cluster_size,
        "similarity_threshold": record.similarity_threshold,
        "window_seconds": record.window_seconds,
        "occurred_at": record.occurred_at,
        "metadata_json": dict(record.metadata),
    }


def _record_from_row(row: SemanticCircuitEventRow) -> SemanticCircuitEventRecord:
    return SemanticCircuitEventRecord(
        event_id=str(row.event_id),
        tenant_id=row.tenant_id,
        channel=row.channel,
        state=row.state,
        trigger_ticket_id=(
            str(row.trigger_ticket_id) if row.trigger_ticket_id is not None else None
        ),
        cluster_size=row.cluster_size,
        similarity_threshold=row.similarity_threshold,
        window_seconds=row.window_seconds,
        occurred_at=row.occurred_at,
        metadata=dict(row.metadata_json or {}),
    )


def _assert_tenant(tenant_id: str, expected_tenant_id: str) -> None:
    if tenant_id != expected_tenant_id:
        raise ValueError("tenant_id does not match expected_tenant_id")


__all__ = [
    "SemanticCircuitEventRecord",
    "SemanticCircuitEventRepository",
]
