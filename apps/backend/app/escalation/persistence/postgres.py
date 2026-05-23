"""Postgres implementation of escalation persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Select, update, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError

from app.escalation.db.models import EscalationRecordRow
from app.escalation.exceptions import EscalationPersistenceError
from app.escalation.persistence.models import EscalationPage, EscalationQuery
from app.escalation.persistence.records import EscalationRecord
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
