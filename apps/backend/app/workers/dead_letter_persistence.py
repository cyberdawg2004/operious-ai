"""Durable dead-letter records for worker retry exhaustion."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import sentry_sdk
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import BaseRepository
from app.runtime.db.models import DeadLetterTaskRow
from app.tenant.db.models import TenantRow

_logger = logging.getLogger(__name__)


def _empty_metadata() -> Mapping[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class DeadLetterTaskRecord:
    dead_letter_task_id: uuid.UUID
    tenant_id: str
    task_name: str
    task_id: str
    execution_id: uuid.UUID | None
    queue: str | None
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
        stmt = (
            pg_insert(DeadLetterTaskRow)
            .values(
                dead_letter_task_id=record.dead_letter_task_id,
                tenant_id=record.tenant_id,
                task_name=record.task_name,
                task_id=record.task_id,
                execution_id=record.execution_id,
                queue=record.queue,
                reason=record.reason,
                retry_count=record.retry_count,
                created_at=record.created_at,
                metadata_json=dict(record.metadata),
            )
            .on_conflict_do_nothing()
        )
        result = await self.session.execute(stmt)
        inserted = getattr(result, "rowcount", 0) == 1
        if inserted:
            _capture_dead_letter_alert(record)
            return record

        existing = await self.get_dead_letter_task(
            record.dead_letter_task_id,
            expected_tenant_id=record.tenant_id,
        )
        if existing is None:
            existing = await self.get_dead_letter_task_by_task_identity(
                task_name=record.task_name,
                task_id=record.task_id,
                expected_tenant_id=record.tenant_id,
            )
        logged_id = (
            existing.dead_letter_task_id
            if existing is not None
            else record.dead_letter_task_id
        )
        _logger.info(
            "dlq_replay_idempotent_write",
            extra={
                "dead_letter_task_id": str(logged_id),
                "tenant_id": record.tenant_id,
                "task_name": record.task_name,
                "task_id": record.task_id,
                "execution_id": (
                    str(record.execution_id)
                    if record.execution_id is not None
                    else None
                ),
                "attempt_count": record.metadata.get("attempt_count"),
            },
        )
        return existing or record

    async def get_dead_letter_task_by_task_identity(
        self,
        *,
        task_name: str,
        task_id: str,
        expected_tenant_id: str | None = None,
    ) -> DeadLetterTaskRecord | None:
        stmt = select(DeadLetterTaskRow).where(
            DeadLetterTaskRow.task_name == task_name,
            DeadLetterTaskRow.task_id == task_id,
        )
        if expected_tenant_id is not None:
            stmt = stmt.where(DeadLetterTaskRow.tenant_id == expected_tenant_id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return _row_to_record(row) if row else None

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
    execution_id: str | uuid.UUID,
    session_id: str,
    attempt_count: int,
    reason: str,
    retry_count: int,
    queue: str | None = None,
    created_at: datetime | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DeadLetterTaskRecord:
    """Persist one dead-letter task and emit the Sentry alert hook."""

    parsed_execution_id = _parse_execution_id(execution_id)
    record = DeadLetterTaskRecord(
        dead_letter_task_id=derive_dead_letter_task_id(
            tenant_id=tenant_id,
            execution_id=parsed_execution_id,
            session_id=session_id,
            attempt_count=attempt_count,
        ),
        tenant_id=tenant_id,
        task_name=task_name,
        task_id=task_id,
        execution_id=parsed_execution_id,
        queue=queue,
        reason=reason,
        retry_count=retry_count,
        created_at=created_at or datetime.now(timezone.utc),
        metadata={
            **dict(metadata or {}),
            "execution_id": str(parsed_execution_id),
            "session_id": session_id,
            "tenant_id": tenant_id,
            "attempt_count": attempt_count,
        },
    )
    return await PostgresDeadLetterTaskPersistence(session).record_dead_letter_task(
        record
    )


def derive_dead_letter_task_id(
    *,
    tenant_id: str,
    execution_id: str | uuid.UUID,
    session_id: str,
    attempt_count: int,
) -> uuid.UUID:
    if attempt_count < 0:
        raise ValueError("attempt_count must be >= 0")
    return uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"dlq:{tenant_id}:{execution_id}:{session_id}:{attempt_count}",
    )


def _capture_dead_letter_alert(record: DeadLetterTaskRecord) -> None:
    del record
    sentry_sdk.capture_message(
        "dead_letter_task_created",
        level="error",
    )


def _parse_execution_id(value: str | uuid.UUID) -> uuid.UUID:
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
        queue=row.queue,
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
