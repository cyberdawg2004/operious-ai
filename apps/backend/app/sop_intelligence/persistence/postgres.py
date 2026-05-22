"""Postgres implementation of SOP intelligence approval persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError

from app.repositories.base import BaseRepository
from app.sop_intelligence.db.models import ApprovalRecordRow
from app.sop_intelligence.exceptions import (
    SOPIntelligencePersistenceError,
)
from app.sop_intelligence.persistence.models import (
    ApprovalPage,
    ApprovalQuery,
)
from app.sop_intelligence.persistence.records import ApprovalRecord
from app.tenant.db.models import TenantKnowledgeDocumentRow


class PostgresSOPApprovalPersistence(BaseRepository):
    """Postgres-backed approval proposal persistence."""

    async def create_approval_record(
        self,
        record: ApprovalRecord,
        *,
        expected_tenant_id: str,
    ) -> None:
        _enforce_expected_tenant(record.tenant_id, expected_tenant_id)
        if not await self._document_visible(
            record.document_id,
            expected_tenant_id=expected_tenant_id,
        ):
            raise SOPIntelligencePersistenceError(
                "approval document_id is not visible for expected_tenant_id"
            )
        row = _record_to_row(record)
        try:
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError as exc:
            raise SOPIntelligencePersistenceError(
                f"approval {record.approval_id!r} already recorded"
            ) from exc

    async def update_approval_record(
        self,
        record: ApprovalRecord,
        *,
        expected_tenant_id: str,
    ) -> None:
        _enforce_expected_tenant(record.tenant_id, expected_tenant_id)
        if not await self._document_visible(
            record.document_id,
            expected_tenant_id=expected_tenant_id,
        ):
            raise SOPIntelligencePersistenceError(
                "approval document_id is not visible for expected_tenant_id"
            )
        row = await self._approval_row(
            record.approval_id,
            expected_tenant_id=expected_tenant_id,
        )
        if row is None:
            raise SOPIntelligencePersistenceError(
                f"approval {record.approval_id!r} not found"
            )
        try:
            async with self.session.begin_nested():
                _update_row(row, record)
        except IntegrityError as exc:
            raise SOPIntelligencePersistenceError(
                f"approval {record.approval_id!r} could not be updated"
            ) from exc

    async def get_approval_record(
        self,
        approval_id: str,
        *,
        expected_tenant_id: str,
    ) -> ApprovalRecord | None:
        row = await self._approval_row(
            approval_id,
            expected_tenant_id=expected_tenant_id,
        )
        return None if row is None else _row_to_record(row)

    async def list_approval_records(
        self,
        query: ApprovalQuery,
        *,
        expected_tenant_id: str,
    ) -> ApprovalPage:
        stmt = select(ApprovalRecordRow).where(
            ApprovalRecordRow.tenant_id == expected_tenant_id
        )
        stmt = _apply_filters(stmt, query=query)
        stmt = stmt.order_by(
            ApprovalRecordRow.created_at,
            ApprovalRecordRow.approval_id,
        )
        all_rows = list((await self.session.execute(stmt)).scalars().all())
        total = len(all_rows)
        sliced = all_rows[query.offset : query.offset + query.limit]
        return ApprovalPage(
            items=tuple(_row_to_record(row) for row in sliced),
            total=total,
            offset=query.offset,
        )

    async def _document_visible(
        self,
        document_id: str,
        *,
        expected_tenant_id: str,
    ) -> bool:
        stmt = select(TenantKnowledgeDocumentRow.document_id).where(
            TenantKnowledgeDocumentRow.document_id == UUID(document_id),
            TenantKnowledgeDocumentRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def _approval_row(
        self,
        approval_id: str,
        *,
        expected_tenant_id: str,
    ) -> ApprovalRecordRow | None:
        stmt = select(ApprovalRecordRow).where(
            ApprovalRecordRow.approval_id == UUID(approval_id),
            ApprovalRecordRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


def _apply_filters(
    stmt: Select[tuple[ApprovalRecordRow]],
    *,
    query: ApprovalQuery,
) -> Select[tuple[ApprovalRecordRow]]:
    if query.approval_id is not None:
        stmt = stmt.where(
            ApprovalRecordRow.approval_id == UUID(query.approval_id)
        )
    if query.tenant_id is not None:
        stmt = stmt.where(ApprovalRecordRow.tenant_id == query.tenant_id)
    if query.document_id is not None:
        stmt = stmt.where(ApprovalRecordRow.document_id == UUID(query.document_id))
    if query.status is not None:
        stmt = stmt.where(ApprovalRecordRow.status == query.status)
    if query.min_confidence is not None:
        stmt = stmt.where(ApprovalRecordRow.confidence >= query.min_confidence)
    return stmt


def _record_to_row(record: ApprovalRecord) -> ApprovalRecordRow:
    return ApprovalRecordRow(
        approval_id=UUID(record.approval_id),
        tenant_id=record.tenant_id,
        document_id=UUID(record.document_id),
        proposed_change=record.proposed_change,
        evidence_sessions=list(record.evidence_sessions),
        confidence=record.confidence,
        status=record.status,
        proposed_by=record.proposed_by,
        reviewed_by=record.reviewed_by,
        created_at=datetime.fromisoformat(record.created_at),
        metadata_json=dict(record.metadata),
    )


def _update_row(row: ApprovalRecordRow, record: ApprovalRecord) -> None:
    row.document_id = UUID(record.document_id)
    row.proposed_change = record.proposed_change
    row.evidence_sessions = list(record.evidence_sessions)
    row.confidence = record.confidence
    row.status = record.status
    row.proposed_by = record.proposed_by
    row.reviewed_by = record.reviewed_by
    row.created_at = datetime.fromisoformat(record.created_at)
    row.metadata_json = dict(record.metadata)


def _row_to_record(row: ApprovalRecordRow) -> ApprovalRecord:
    return ApprovalRecord(
        approval_id=str(row.approval_id),
        tenant_id=row.tenant_id,
        document_id=str(row.document_id),
        proposed_change=row.proposed_change,
        evidence_sessions=tuple(_as_list_of_str(row.evidence_sessions)),
        confidence=row.confidence,
        status=row.status,
        proposed_by=row.proposed_by,
        reviewed_by=row.reviewed_by,
        created_at=row.created_at.isoformat(),
        metadata=dict(_as_dict(row.metadata_json)),
    )


def _enforce_expected_tenant(
    tenant_id: str,
    expected_tenant_id: str,
) -> None:
    if tenant_id != expected_tenant_id:
        raise SOPIntelligencePersistenceError(
            "approval tenant_id does not match expected_tenant_id"
        )


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}  # pyright: ignore[reportUnknownArgumentType,reportUnknownVariableType]
    return {}


def _as_list_of_str(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in cast(list[object], value)]
    return []


__all__ = ["PostgresSOPApprovalPersistence"]
