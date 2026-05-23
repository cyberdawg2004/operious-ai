"""Durable dead-letter records for worker retry exhaustion."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import sentry_sdk
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deterministic_identity import derive_runtime_id
from app.db.repository import BaseRepository
from app.runtime.db.models import DeadLetterTaskRow
from app.tenant.db.models import TenantRow

_DEAD_LETTER_TASK_NAMESPACE = uuid.UUID("8ee257e8-99d4-5cdf-9baa-02eb42cc7c01")


def _empty_metadata() -> Mapping[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class DeadLetterTaskRecord:
    dead_letter_task_id: uuid.UUID
    tenant_id: str
    task_name: str
    task_id: str
    execution_id: uuid.UUID | None
    reason: str
    retry_count: int
    created_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)


class PostgresDeadLetterTaskPersistence(BaseRepository):
    """Postgres-backed dead-letter task sink."""

    async def record_dead_letter_task(
        self,
        record: DeadLetterTaskRecord,
    ) -> DeadLetterTaskRecord:
        await self.session.merge(TenantRow(tenant_id=record.tenant_id))
        existing = await self.session.get(
            DeadLetterTaskRow,
            record.dead_letter_task_id,
        )
        if existing is not None:
            return _row_to_record(existing)
        row = DeadLetterTaskRow(
            dead_letter_task_id=record.dead_letter_task_id,
            tenant_id=record.tenant_id,
            task_name=record.task_name,
            task_id=record.task_id,
            execution_id=record.execution_id,
            reason=record.reason,
            retry_count=record.retry_count,
            created_at=record.created_at,
            metadata_json=dict(record.metadata),
        )
        self.session.add(row)
        await self.session.flush()
        _capture_dead_letter_alert(record)
        return record

    async def get_dead_letter_task(
        self,
        dead_letter_task_id: uuid.UUID,
        *,
        expected_tenant_id: str | None = None,
    ) -> DeadLetterTaskRecord | None:
        stmt = select(DeadLetterTaskRow).where(
            DeadLetterTaskRow.dead_letter_task_id == dead_letter_task_id
        )
        if expected_tenant_id is not None:
            stmt = stmt.where(DeadLetterTaskRow.tenant_id == expected_tenant_id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_record(row)


async def record_dead_letter_task(
    *,
    session: AsyncSession,
    tenant_id: str,
    task_name: str,
    task_id: str,
    reason: str,
    retry_count: int,
    execution_id: str | uuid.UUID | None = None,
    created_at: datetime | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DeadLetterTaskRecord:
    """Persist one dead-letter task and emit the Sentry alert hook."""

    parsed_execution_id = _parse_execution_id(execution_id)
    record = DeadLetterTaskRecord(
        dead_letter_task_id=derive_dead_letter_task_id(
            tenant_id=tenant_id,
            task_name=task_name,
            task_id=task_id,
            execution_id=parsed_execution_id,
        ),
        tenant_id=tenant_id,
        task_name=task_name,
        task_id=task_id,
        execution_id=parsed_execution_id,
        reason=reason,
        retry_count=retry_count,
        created_at=created_at or datetime.now(timezone.utc),
        metadata=dict(metadata or {}),
    )
    return await PostgresDeadLetterTaskPersistence(session).record_dead_letter_task(
        record
    )


def derive_dead_letter_task_id(
    *,
    tenant_id: str,
    task_name: str,
    task_id: str,
    execution_id: uuid.UUID | None,
) -> uuid.UUID:
    return derive_runtime_id(
        namespace=_DEAD_LETTER_TASK_NAMESPACE,
        tenant_id=tenant_id,
        seed_components=(
            "dead_letter_task",
            task_name,
            task_id,
            str(execution_id) if execution_id is not None else "",
        ),
    )


def _capture_dead_letter_alert(record: DeadLetterTaskRecord) -> None:
    del record
    sentry_sdk.capture_message(
        "dead_letter_task_created",
        level="error",
    )


def _parse_execution_id(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(value)


def _row_to_record(row: DeadLetterTaskRow) -> DeadLetterTaskRecord:
    return DeadLetterTaskRecord(
        dead_letter_task_id=row.dead_letter_task_id,
        tenant_id=row.tenant_id,
        task_name=row.task_name,
        task_id=row.task_id,
        execution_id=row.execution_id,
        reason=row.reason,
        retry_count=row.retry_count,
        created_at=row.created_at,
        metadata=dict(row.metadata_json),
    )


__all__ = [
    "DeadLetterTaskRecord",
    "PostgresDeadLetterTaskPersistence",
    "derive_dead_letter_task_id",
    "record_dead_letter_task",
]
