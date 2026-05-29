"""Append-only crisis event audit repository."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import Select, select
from sqlalchemy.dialects import postgresql, sqlite

from app.governance.db.models import CrisisEventRow
from app.repositories.base import BaseRepository

_EVENT_KINDS = frozenset({"deployed", "deactivated", "expired"})


@dataclass(frozen=True)
class CrisisEventRecord:
    event_id: str
    tenant_id: str
    deployment_id: str
    event_kind: str
    template: str
    scope_json: dict[str, Any]
    ttl_minutes: int
    actor: str
    occurred_at: datetime
    metadata: dict[str, Any]


class CrisisEventRepository(Protocol):
    async def write(self, record: CrisisEventRecord) -> None:
        """Insert one immutable event. No update/delete methods exist."""
        ...

    async def list_for_tenant(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        limit: int = 100,
        since: datetime | None = None,
    ) -> list[CrisisEventRecord]:
        """List tenant-visible events newest first."""
        ...


class PostgresCrisisEventRepository(BaseRepository):
    """INSERT-only repository for the append-only crisis event table."""

    async def write(self, record: CrisisEventRecord) -> None:
        _assert_tenant(record.tenant_id, record.tenant_id)
        if record.event_kind not in _EVENT_KINDS:
            raise ValueError("unsupported crisis event kind")
        values = _record_values(record)
        dialect_name = self.session.get_bind().dialect.name
        if dialect_name == "sqlite":
            statement = (
                sqlite.insert(CrisisEventRow)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["event_id"])
            )
        else:
            statement = (
                postgresql.insert(CrisisEventRow)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["event_id"])
            )
        await self.session.execute(statement)

    async def list_for_tenant(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        limit: int = 100,
        since: datetime | None = None,
    ) -> list[CrisisEventRecord]:
        _assert_tenant(tenant_id, expected_tenant_id)
        bounded_limit = max(1, min(limit, 500))
        statement: Select[tuple[CrisisEventRow]] = select(CrisisEventRow).where(
            CrisisEventRow.tenant_id == tenant_id
        )
        if since is not None:
            statement = statement.where(CrisisEventRow.occurred_at >= since)
        rows = (
            await self.session.scalars(
                statement.order_by(CrisisEventRow.occurred_at.desc()).limit(
                    bounded_limit
                )
            )
        ).all()
        return [_record_from_row(row) for row in rows]


def _record_values(record: CrisisEventRecord) -> Mapping[str, Any]:
    return {
        "event_id": uuid.UUID(record.event_id),
        "tenant_id": record.tenant_id,
        "deployment_id": uuid.UUID(record.deployment_id),
        "event_kind": record.event_kind,
        "template": record.template,
        "scope_json": dict(record.scope_json),
        "ttl_minutes": record.ttl_minutes,
        "actor": record.actor,
        "occurred_at": record.occurred_at,
        "metadata_json": dict(record.metadata),
    }


def _record_from_row(row: CrisisEventRow) -> CrisisEventRecord:
    return CrisisEventRecord(
        event_id=str(row.event_id),
        tenant_id=row.tenant_id,
        deployment_id=str(row.deployment_id),
        event_kind=row.event_kind,
        template=row.template,
        scope_json=dict(row.scope_json or {}),
        ttl_minutes=row.ttl_minutes,
        actor=row.actor,
        occurred_at=row.occurred_at,
        metadata=dict(row.metadata_json or {}),
    )


def _assert_tenant(tenant_id: str, expected_tenant_id: str) -> None:
    if tenant_id != expected_tenant_id:
        raise ValueError("tenant_id does not match expected_tenant_id")


__all__ = [
    "CrisisEventRecord",
    "CrisisEventRepository",
    "PostgresCrisisEventRepository",
]
