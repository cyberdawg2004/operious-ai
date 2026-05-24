"""Postgres implementation of escalation persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Select, update, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError

from app.escalation.db.models import EscalationOutboxRow, EscalationRecordRow
from app.escalation.enums import EscalationOutboxStatus
from app.escalation.exceptions import EscalationPersistenceError
from app.escalation.persistence.models import (
    EscalationOutboxPage,
    EscalationOutboxQuery,
    EscalationPage,
    EscalationQuery,
)
from app.escalation.persistence.records import (
    EscalationOutboxRecord,
    EscalationRecord,
)
from app.repositories.base import BaseRepository
from app.repositories.pagination import fetch_scalar_page


class PostgresEscalationPersistence(BaseRepository):
    """Postgres-backed escalation record persistence."""

    async def create_escalation(
        self,
        record: EscalationRecord,
        *,
        expected_tenant_id: str | None = None,
    ) -> None:
        _enforce_expected_tenant(record.tenant_id, expected_tenant_id)
        row = _record_to_row(record)
        try:
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError as exc:
            raise EscalationPersistenceError(
                f"escalation {record.escalation_id!r} already recorded"
            ) from exc

    async def update_escalation(
        self,
        record: EscalationRecord,
        *,
        expected_tenant_id: str | None = None,
    ) -> None:
        _enforce_expected_tenant(record.tenant_id, expected_tenant_id)
        stmt = (
            update(EscalationRecordRow)
            .where(
                EscalationRecordRow.escalation_id
                == UUID(record.escalation_id)
            )
            .values(
                session_id=UUID(record.session_id),
                tenant_id=record.tenant_id,
                reason=record.reason,
                governance_decision_id=UUID(record.governance_decision_id),
                status=record.status,
                created_at=datetime.fromisoformat(record.created_at),
                resolved_at=(
                    datetime.fromisoformat(record.resolved_at)
                    if record.resolved_at is not None
                    else None
                ),
                resolution=record.resolution,
                resolved_by=record.resolved_by,
                metadata_json=dict(record.metadata),
            )
        )
        if expected_tenant_id is not None:
            stmt = stmt.where(EscalationRecordRow.tenant_id == expected_tenant_id)
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            raise EscalationPersistenceError(
                f"unknown escalation {record.escalation_id!r}"
            )

    async def get_escalation(
        self,
        escalation_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> EscalationRecord | None:
        stmt = select(EscalationRecordRow).where(
            EscalationRecordRow.escalation_id == UUID(escalation_id)
        )
        if expected_tenant_id is not None:
            stmt = stmt.where(EscalationRecordRow.tenant_id == expected_tenant_id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_record(row)

    async def get_escalation_for_governance_decision(
        self,
        governance_decision_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> EscalationRecord | None:
        stmt = select(EscalationRecordRow).where(
            EscalationRecordRow.governance_decision_id
            == UUID(governance_decision_id)
        )
        if expected_tenant_id is not None:
            stmt = stmt.where(EscalationRecordRow.tenant_id == expected_tenant_id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_record(row)

    async def list_escalations(
        self,
        query: EscalationQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> EscalationPage:
        stmt = select(EscalationRecordRow)
        stmt = _apply_filters(
            stmt,
            query=query,
            expected_tenant_id=expected_tenant_id,
        )
        stmt = stmt.order_by(
            EscalationRecordRow.created_at,
            EscalationRecordRow.escalation_id,
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return EscalationPage(
            items=tuple(_row_to_record(row) for row in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def save_escalation_outbox(
        self,
        record: EscalationOutboxRecord,
        *,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxRecord:
        _enforce_expected_tenant(record.tenant_id, expected_tenant_id)
        existing = await self.get_escalation_outbox_by_escalation(
            record.escalation_id,
            expected_tenant_id=expected_tenant_id,
        )
        if existing is not None:
            return existing
        try:
            async with self.session.begin_nested():
                self.session.add(_outbox_record_to_row(record))
        except IntegrityError as exc:
            existing = await self.get_escalation_outbox_by_escalation(
                record.escalation_id,
                expected_tenant_id=expected_tenant_id,
            )
            if existing is not None:
                return existing
            raise EscalationPersistenceError(
                f"escalation outbox {record.outbox_id!r} could not be persisted"
            ) from exc
        return record

    async def get_escalation_outbox(
        self,
        outbox_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxRecord | None:
        stmt = select(EscalationOutboxRow).where(
            EscalationOutboxRow.outbox_id == UUID(outbox_id)
        )
        if expected_tenant_id is not None:
            stmt = stmt.where(EscalationOutboxRow.tenant_id == expected_tenant_id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _outbox_row_to_record(row)

    async def get_escalation_outbox_by_escalation(
        self,
        escalation_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxRecord | None:
        stmt = select(EscalationOutboxRow).where(
            EscalationOutboxRow.escalation_id == UUID(escalation_id)
        )
        if expected_tenant_id is not None:
            stmt = stmt.where(EscalationOutboxRow.tenant_id == expected_tenant_id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _outbox_row_to_record(row)

    async def claim_escalation_outbox(
        self,
        *,
        escalation_id: str,
        publisher_id: str,
        claim_id: str,
        claimed_at: datetime,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxRecord | None:
        stmt = (
            update(EscalationOutboxRow)
            .where(
                EscalationOutboxRow.escalation_id == UUID(escalation_id),
                EscalationOutboxRow.status
                == EscalationOutboxStatus.PENDING.value,
            )
            .values(
                status=EscalationOutboxStatus.PUBLISHING.value,
                claimed_at=claimed_at,
                publisher_id=publisher_id,
                claim_id=UUID(claim_id),
                republish_count=EscalationOutboxRow.republish_count + 1,
                last_error=None,
            )
        )
        if expected_tenant_id is not None:
            stmt = stmt.where(EscalationOutboxRow.tenant_id == expected_tenant_id)
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            return None
        return await self.get_escalation_outbox_by_escalation(
            escalation_id,
            expected_tenant_id=expected_tenant_id,
        )

    async def mark_escalation_outbox_published(
        self,
        *,
        outbox_id: str,
        claim_id: str,
        published_at: datetime,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxRecord:
        current = await self.get_escalation_outbox(
            outbox_id,
            expected_tenant_id=expected_tenant_id,
        )
        if current is None:
            raise EscalationPersistenceError(
                f"unknown escalation outbox {outbox_id!r}"
            )
        if current.status is EscalationOutboxStatus.PUBLISHED:
            if current.claim_id == claim_id:
                return current
            raise EscalationPersistenceError(
                "escalation outbox publish claim does not match"
            )
        stmt = (
            update(EscalationOutboxRow)
            .where(
                EscalationOutboxRow.outbox_id == UUID(outbox_id),
                EscalationOutboxRow.status
                == EscalationOutboxStatus.PUBLISHING.value,
                EscalationOutboxRow.claim_id == UUID(claim_id),
            )
            .values(
                status=EscalationOutboxStatus.PUBLISHED.value,
                published_at=published_at,
                dead_letter=False,
                last_error=None,
            )
        )
        if expected_tenant_id is not None:
            stmt = stmt.where(EscalationOutboxRow.tenant_id == expected_tenant_id)
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            raise EscalationPersistenceError(
                "only the active escalation outbox claim can be published"
            )
        record = await self.get_escalation_outbox(
            outbox_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record is None:
            raise EscalationPersistenceError(
                f"unknown escalation outbox {outbox_id!r}"
            )
        return record

    async def mark_escalation_outbox_failed(
        self,
        *,
        outbox_id: str,
        claim_id: str,
        error: str,
        failed_at: datetime,
        dead_letter: bool = False,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxRecord:
        record = await self.get_escalation_outbox(
            outbox_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record is None:
            raise EscalationPersistenceError(
                f"unknown escalation outbox {outbox_id!r}"
            )
        if record.status is EscalationOutboxStatus.FAILED:
            if record.claim_id == claim_id:
                return record
            raise EscalationPersistenceError(
                "escalation outbox failure claim does not match"
            )
        if (
            record.status is not EscalationOutboxStatus.PUBLISHING
            or record.claim_id != claim_id
        ):
            raise EscalationPersistenceError(
                "only the active escalation outbox claim can fail publication"
            )
        stmt = (
            update(EscalationOutboxRow)
            .where(
                EscalationOutboxRow.outbox_id == UUID(outbox_id),
                EscalationOutboxRow.status
                == EscalationOutboxStatus.PUBLISHING.value,
                EscalationOutboxRow.claim_id == UUID(claim_id),
            )
            .values(
                status=EscalationOutboxStatus.FAILED.value,
                dead_letter=dead_letter,
                last_error=error,
                metadata_json={
                    **dict(record.metadata),
                    "failed_at": failed_at.isoformat(),
                },
            )
        )
        if expected_tenant_id is not None:
            stmt = stmt.where(EscalationOutboxRow.tenant_id == expected_tenant_id)
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            raise EscalationPersistenceError(
                f"unknown escalation outbox {outbox_id!r}"
            )
        updated = await self.get_escalation_outbox(
            outbox_id,
            expected_tenant_id=expected_tenant_id,
        )
        if updated is None:
            raise EscalationPersistenceError(
                f"unknown escalation outbox {outbox_id!r}"
            )
        return updated

    async def requeue_stale_escalation_outbox(
        self,
        *,
        outbox_id: str,
        stale_before: datetime,
        requeued_at: datetime,
        reason: str,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxRecord | None:
        record = await self.get_escalation_outbox(
            outbox_id,
            expected_tenant_id=expected_tenant_id,
        )
        if (
            record is None
            or record.status is not EscalationOutboxStatus.PUBLISHING
            or record.claimed_at is None
            or record.claimed_at >= stale_before
        ):
            return None
        stmt = (
            update(EscalationOutboxRow)
            .where(EscalationOutboxRow.outbox_id == UUID(outbox_id))
            .values(
                status=EscalationOutboxStatus.PENDING.value,
                claimed_at=None,
                publisher_id=None,
                claim_id=None,
                last_error=reason,
                metadata_json={
                    **dict(record.metadata),
                    "requeued_at": requeued_at.isoformat(),
                    "requeue_reason": reason,
                },
            )
        )
        if expected_tenant_id is not None:
            stmt = stmt.where(EscalationOutboxRow.tenant_id == expected_tenant_id)
        await self.session.execute(stmt)
        return await self.get_escalation_outbox(
            outbox_id,
            expected_tenant_id=expected_tenant_id,
        )

    async def list_escalation_outbox(
        self,
        query: EscalationOutboxQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> EscalationOutboxPage:
        stmt = select(EscalationOutboxRow)
        stmt = _apply_outbox_filters(
            stmt,
            query=query,
            expected_tenant_id=expected_tenant_id,
        )
        stmt = stmt.order_by(
            EscalationOutboxRow.created_at,
            EscalationOutboxRow.outbox_id,
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return EscalationOutboxPage(
            items=tuple(_outbox_row_to_record(row) for row in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )


def _apply_filters(
    stmt: Select[tuple[EscalationRecordRow]],
    *,
    query: EscalationQuery,
    expected_tenant_id: str | None,
) -> Select[tuple[EscalationRecordRow]]:
    if expected_tenant_id is not None:
        stmt = stmt.where(EscalationRecordRow.tenant_id == expected_tenant_id)
    if query.escalation_id is not None:
        stmt = stmt.where(
            EscalationRecordRow.escalation_id == UUID(query.escalation_id)
        )
    if query.session_id is not None:
        stmt = stmt.where(EscalationRecordRow.session_id == UUID(query.session_id))
    if query.governance_decision_id is not None:
        stmt = stmt.where(
            EscalationRecordRow.governance_decision_id
            == UUID(query.governance_decision_id)
        )
    if query.tenant_id is not None:
        stmt = stmt.where(EscalationRecordRow.tenant_id == query.tenant_id)
    if query.status is not None:
        stmt = stmt.where(EscalationRecordRow.status == query.status)
    return stmt


def _apply_outbox_filters(
    stmt: Select[tuple[EscalationOutboxRow]],
    *,
    query: EscalationOutboxQuery,
    expected_tenant_id: str | None,
) -> Select[tuple[EscalationOutboxRow]]:
    if expected_tenant_id is not None:
        stmt = stmt.where(EscalationOutboxRow.tenant_id == expected_tenant_id)
    if query.outbox_id is not None:
        stmt = stmt.where(EscalationOutboxRow.outbox_id == UUID(query.outbox_id))
    if query.escalation_id is not None:
        stmt = stmt.where(
            EscalationOutboxRow.escalation_id == UUID(query.escalation_id)
        )
    if query.tenant_id is not None:
        stmt = stmt.where(EscalationOutboxRow.tenant_id == query.tenant_id)
    if query.status is not None:
        stmt = stmt.where(EscalationOutboxRow.status == query.status.value)
    if query.claimed_before_or_at is not None:
        stmt = stmt.where(
            EscalationOutboxRow.claimed_at.is_not(None),
            EscalationOutboxRow.claimed_at <= query.claimed_before_or_at,
        )
    return stmt


def _record_to_row(record: EscalationRecord) -> EscalationRecordRow:
    return EscalationRecordRow(
        escalation_id=UUID(record.escalation_id),
        session_id=UUID(record.session_id),
        tenant_id=record.tenant_id,
        reason=record.reason,
        governance_decision_id=UUID(record.governance_decision_id),
        status=record.status,
        created_at=datetime.fromisoformat(record.created_at),
        resolved_at=(
            datetime.fromisoformat(record.resolved_at)
            if record.resolved_at is not None
            else None
        ),
        resolution=record.resolution,
        resolved_by=record.resolved_by,
        metadata_json=dict(record.metadata),
    )


def _row_to_record(row: EscalationRecordRow) -> EscalationRecord:
    return EscalationRecord(
        escalation_id=str(row.escalation_id),
        session_id=str(row.session_id),
        tenant_id=row.tenant_id,
        reason=row.reason,
        governance_decision_id=str(row.governance_decision_id),
        status=row.status,
        created_at=row.created_at.isoformat(),
        resolved_at=(
            row.resolved_at.isoformat()
            if row.resolved_at is not None
            else None
        ),
        resolution=row.resolution,
        resolved_by=row.resolved_by,
        metadata=dict(_as_dict(row.metadata_json)),
    )


def _outbox_record_to_row(record: EscalationOutboxRecord) -> EscalationOutboxRow:
    return EscalationOutboxRow(
        outbox_id=UUID(record.outbox_id),
        escalation_id=UUID(record.escalation_id),
        tenant_id=record.tenant_id,
        status=record.status.value,
        created_at=record.created_at,
        claimed_at=record.claimed_at,
        published_at=record.published_at,
        claim_id=UUID(record.claim_id) if record.claim_id is not None else None,
        publisher_id=record.publisher_id,
        republish_count=record.republish_count,
        dead_letter=record.dead_letter,
        last_error=record.last_error,
        metadata_json=dict(record.metadata),
    )


def _outbox_row_to_record(row: EscalationOutboxRow) -> EscalationOutboxRecord:
    return EscalationOutboxRecord(
        outbox_id=str(row.outbox_id),
        escalation_id=str(row.escalation_id),
        tenant_id=row.tenant_id,
        status=EscalationOutboxStatus(row.status),
        created_at=row.created_at,
        claimed_at=row.claimed_at,
        published_at=row.published_at,
        claim_id=str(row.claim_id) if row.claim_id is not None else None,
        publisher_id=row.publisher_id,
        republish_count=row.republish_count,
        dead_letter=row.dead_letter,
        last_error=row.last_error,
        metadata=dict(_as_dict(row.metadata_json)),
    )


def _enforce_expected_tenant(
    tenant_id: str,
    expected_tenant_id: str | None,
) -> None:
    if expected_tenant_id is not None and tenant_id != expected_tenant_id:
        raise EscalationPersistenceError(
            "escalation tenant_id does not match expected_tenant_id"
        )


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}  # pyright: ignore[reportUnknownArgumentType,reportUnknownVariableType]
    return {}


__all__ = ["PostgresEscalationPersistence"]
