"""Postgres implementation of case approval persistence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Select, case, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError

from app.approvals.db.models import (
    CaseApprovalOutboxRow,
    CaseApprovalRecordRow,
)
from app.approvals.enums import (
    CaseApprovalEntryCategory,
    CaseApprovalOutboxStatus,
    CaseApprovalStatus,
)
from app.approvals.exceptions import CaseApprovalPersistenceError
from app.approvals.persistence.models import (
    CaseApprovalOutboxPage,
    CaseApprovalOutboxQuery,
    CaseApprovalPage,
    CaseApprovalQuery,
)
from app.approvals.persistence.records import (
    CaseApprovalOutboxRecord,
    CaseApprovalRecord,
)
from app.data_protection.crypto import DataProtectionService
from app.repositories.base import BaseRepository
from app.repositories.pagination import fetch_scalar_page


class PostgresCaseApprovalPersistence(BaseRepository):
    """Postgres-backed case approval persistence."""

    def __init__(
        self,
        session: Any,
        *,
        data_protection: DataProtectionService | None = None,
    ) -> None:
        super().__init__(session)
        self._data_protection = data_protection

    async def create_case(
        self,
        record: CaseApprovalRecord,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalRecord:
        _enforce_expected_tenant(record.tenant_id, expected_tenant_id)
        protected = await self._protect_case(record)
        try:
            async with self.session.begin_nested():
                self.session.add(_record_to_row(protected))
        except IntegrityError:
            existing = await self.get_case_by_dedup_key(
                record.dedup_key,
                expected_tenant_id=expected_tenant_id,
            )
            if existing is not None:
                return existing
            raise
        return record

    async def update_case(
        self,
        record: CaseApprovalRecord,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalRecord:
        _enforce_expected_tenant(record.tenant_id, expected_tenant_id)
        protected = await self._protect_case(record)
        stmt = (
            update(CaseApprovalRecordRow)
            .where(
                CaseApprovalRecordRow.approval_case_id
                == UUID(record.approval_case_id),
                CaseApprovalRecordRow.tenant_id == expected_tenant_id,
            )
            .values(
                session_id=_optional_uuid(protected.session_id),
                execution_id=_optional_uuid(protected.execution_id),
                dispatch_id=_optional_uuid(protected.dispatch_id),
                resolution_proposal_id=_optional_uuid(
                    protected.resolution_proposal_id
                ),
                entry_category=protected.entry_category.value,
                ticket_ref=protected.ticket_ref,
                product=protected.product,
                issue_summary=protected.issue_summary,
                sme_recommendation_id=_optional_uuid(
                    protected.sme_recommendation_id
                ),
                recommended_action=(
                    dict(protected.recommended_action)
                    if protected.recommended_action is not None
                    else None
                ),
                status=protected.status.value,
                guidance_round=protected.guidance_round,
                guidance_ref=protected.guidance_ref,
                governance_decision_id=_optional_uuid(
                    protected.governance_decision_id
                ),
                requested_at=protected.requested_at,
                resolved_at=protected.resolved_at,
                resolved_by=protected.resolved_by,
                resolution_note=protected.resolution_note,
                dedup_key=protected.dedup_key,
                metadata_json=dict(protected.metadata),
            )
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            raise CaseApprovalPersistenceError(
                f"unknown approval case {record.approval_case_id!r}"
            )
        return record

    async def get_case(
        self,
        approval_case_id: str,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalRecord | None:
        stmt = select(CaseApprovalRecordRow).where(
            CaseApprovalRecordRow.approval_case_id == UUID(approval_case_id),
            CaseApprovalRecordRow.tenant_id == expected_tenant_id,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else await self._row_to_record(row)

    async def get_case_by_dedup_key(
        self,
        dedup_key: str,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalRecord | None:
        stmt = select(CaseApprovalRecordRow).where(
            CaseApprovalRecordRow.dedup_key == dedup_key,
            CaseApprovalRecordRow.tenant_id == expected_tenant_id,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else await self._row_to_record(row)

    async def list_cases(
        self,
        query: CaseApprovalQuery,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalPage:
        stmt = select(CaseApprovalRecordRow).where(
            CaseApprovalRecordRow.tenant_id == expected_tenant_id
        )
        stmt = _apply_case_filters(stmt, query=query)
        stmt = stmt.order_by(
            case(
                (
                    CaseApprovalRecordRow.status
                    == CaseApprovalStatus.AWAITING_APPROVAL.value,
                    0,
                ),
                (
                    CaseApprovalRecordRow.status
                    == CaseApprovalStatus.PENDING_SME_REVIEW.value,
                    1,
                ),
                else_=2,
            ),
            CaseApprovalRecordRow.requested_at.desc(),
            CaseApprovalRecordRow.approval_case_id.desc(),
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return CaseApprovalPage(
            items=tuple([await self._row_to_record(row) for row in page.items]),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def save_outbox(
        self,
        record: CaseApprovalOutboxRecord,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalOutboxRecord:
        _enforce_expected_tenant(record.tenant_id, expected_tenant_id)
        existing = await self.get_outbox_by_case(
            record.approval_case_id,
            expected_tenant_id=expected_tenant_id,
        )
        if existing is not None:
            return existing
        try:
            async with self.session.begin_nested():
                self.session.add(_outbox_record_to_row(record))
        except IntegrityError as exc:
            existing = await self.get_outbox_by_case(
                record.approval_case_id,
                expected_tenant_id=expected_tenant_id,
            )
            if existing is not None:
                return existing
            raise CaseApprovalPersistenceError(
                f"approval outbox {record.outbox_id!r} could not be persisted"
            ) from exc
        return record

    async def get_outbox_by_case(
        self,
        approval_case_id: str,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalOutboxRecord | None:
        stmt = select(CaseApprovalOutboxRow).where(
            CaseApprovalOutboxRow.approval_case_id == UUID(approval_case_id),
            CaseApprovalOutboxRow.tenant_id == expected_tenant_id,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _outbox_row_to_record(row)

    async def republish_outbox(
        self,
        record: CaseApprovalOutboxRecord,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalOutboxRecord:
        _enforce_expected_tenant(record.tenant_id, expected_tenant_id)
        existing = await self.get_outbox_by_case(
            record.approval_case_id,
            expected_tenant_id=expected_tenant_id,
        )
        if existing is None:
            return await self.save_outbox(
                record,
                expected_tenant_id=expected_tenant_id,
            )
        stmt = (
            update(CaseApprovalOutboxRow)
            .where(
                CaseApprovalOutboxRow.approval_case_id
                == UUID(record.approval_case_id),
                CaseApprovalOutboxRow.tenant_id == expected_tenant_id,
            )
            .values(
                status=CaseApprovalOutboxStatus.PENDING.value,
                claimed_at=None,
                published_at=None,
                publisher_id=None,
                claim_id=None,
                dead_letter=False,
                last_error=None,
                metadata_json=dict(record.metadata),
            )
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            raise CaseApprovalPersistenceError(
                f"approval outbox for case {record.approval_case_id!r} "
                "could not be reset"
            )
        refreshed = await self.get_outbox_by_case(
            record.approval_case_id,
            expected_tenant_id=expected_tenant_id,
        )
        if refreshed is None:
            raise CaseApprovalPersistenceError(
                f"approval outbox for case {record.approval_case_id!r} missing"
            )
        return refreshed

    async def claim_outbox(
        self,
        *,
        approval_case_id: str,
        publisher_id: str,
        claim_id: str,
        claimed_at: datetime,
        expected_tenant_id: str,
    ) -> CaseApprovalOutboxRecord | None:
        stmt = (
            update(CaseApprovalOutboxRow)
            .where(
                CaseApprovalOutboxRow.approval_case_id == UUID(approval_case_id),
                CaseApprovalOutboxRow.tenant_id == expected_tenant_id,
                CaseApprovalOutboxRow.status
                == CaseApprovalOutboxStatus.PENDING.value,
            )
            .values(
                status=CaseApprovalOutboxStatus.PUBLISHING.value,
                claimed_at=claimed_at,
                publisher_id=publisher_id,
                claim_id=UUID(claim_id),
                republish_count=CaseApprovalOutboxRow.republish_count + 1,
                last_error=None,
            )
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            return None
        return await self.get_outbox_by_case(
            approval_case_id,
            expected_tenant_id=expected_tenant_id,
        )

    async def mark_outbox_published(
        self,
        *,
        outbox_id: str,
        claim_id: str,
        published_at: datetime,
        expected_tenant_id: str,
    ) -> CaseApprovalOutboxRecord:
        return await self._mark_outbox(
            outbox_id=outbox_id,
            claim_id=claim_id,
            expected_tenant_id=expected_tenant_id,
            status=CaseApprovalOutboxStatus.PUBLISHED,
            published_at=published_at,
            error=None,
            dead_letter=False,
        )

    async def mark_outbox_failed(
        self,
        *,
        outbox_id: str,
        claim_id: str,
        error: str,
        failed_at: datetime,
        dead_letter: bool,
        expected_tenant_id: str,
    ) -> CaseApprovalOutboxRecord:
        return await self._mark_outbox(
            outbox_id=outbox_id,
            claim_id=claim_id,
            expected_tenant_id=expected_tenant_id,
            status=CaseApprovalOutboxStatus.FAILED,
            published_at=None,
            error=error,
            dead_letter=dead_letter,
            failed_at=failed_at,
        )

    async def list_outbox(
        self,
        query: CaseApprovalOutboxQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> CaseApprovalOutboxPage:
        stmt = select(CaseApprovalOutboxRow)
        if expected_tenant_id is not None:
            stmt = stmt.where(CaseApprovalOutboxRow.tenant_id == expected_tenant_id)
        if query.tenant_id is not None:
            stmt = stmt.where(CaseApprovalOutboxRow.tenant_id == query.tenant_id)
        if query.status is not None:
            stmt = stmt.where(CaseApprovalOutboxRow.status == query.status)
        if query.dead_letter is not None:
            stmt = stmt.where(CaseApprovalOutboxRow.dead_letter == query.dead_letter)
        stmt = stmt.order_by(
            CaseApprovalOutboxRow.created_at,
            CaseApprovalOutboxRow.outbox_id,
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return CaseApprovalOutboxPage(
            items=tuple(_outbox_row_to_record(row) for row in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def _mark_outbox(
        self,
        *,
        outbox_id: str,
        claim_id: str,
        expected_tenant_id: str,
        status: CaseApprovalOutboxStatus,
        published_at: datetime | None,
        error: str | None,
        dead_letter: bool,
        failed_at: datetime | None = None,
    ) -> CaseApprovalOutboxRecord:
        current = await self._get_outbox(
            outbox_id,
            expected_tenant_id=expected_tenant_id,
        )
        if current is None:
            raise CaseApprovalPersistenceError(
                f"unknown approval outbox {outbox_id!r}"
            )
        if current.claim_id != claim_id:
            raise CaseApprovalPersistenceError(
                "approval outbox claim does not match"
            )
        metadata = dict(current.metadata)
        if failed_at is not None:
            metadata["failed_at"] = failed_at.isoformat()
        stmt = (
            update(CaseApprovalOutboxRow)
            .where(
                CaseApprovalOutboxRow.outbox_id == UUID(outbox_id),
                CaseApprovalOutboxRow.tenant_id == expected_tenant_id,
                CaseApprovalOutboxRow.status
                == CaseApprovalOutboxStatus.PUBLISHING.value,
                CaseApprovalOutboxRow.claim_id == UUID(claim_id),
            )
            .values(
                status=status.value,
                published_at=published_at,
                dead_letter=dead_letter,
                last_error=error,
                metadata_json=metadata,
            )
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        if result.rowcount != 1:
            raise CaseApprovalPersistenceError(
                "only the active approval outbox claim can be resolved"
            )
        updated = await self._get_outbox(
            outbox_id,
            expected_tenant_id=expected_tenant_id,
        )
        if updated is None:
            raise CaseApprovalPersistenceError(
                f"unknown approval outbox {outbox_id!r}"
            )
        return updated

    async def _get_outbox(
        self,
        outbox_id: str,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalOutboxRecord | None:
        stmt = select(CaseApprovalOutboxRow).where(
            CaseApprovalOutboxRow.outbox_id == UUID(outbox_id),
            CaseApprovalOutboxRow.tenant_id == expected_tenant_id,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _outbox_row_to_record(row)

    async def _protect_case(
        self,
        record: CaseApprovalRecord,
    ) -> CaseApprovalRecord:
        if self._data_protection is None:
            return record
        subject_id = record.session_id or record.execution_id or record.approval_case_id
        guidance_ref = (
            await self._data_protection.encrypt_text(
                record.guidance_ref,
                tenant_id=record.tenant_id,
                subject_id=subject_id,
                field="case_approval_records.guidance_ref",
            )
            if record.guidance_ref is not None
            else None
        )
        metadata = await self._data_protection.encrypt_json_values(
            dict(record.metadata),
            tenant_id=record.tenant_id,
            subject_id=subject_id,
            field="case_approval_records.metadata",
        )
        return replace(
            record,
            guidance_ref=guidance_ref,
            metadata=metadata,
        )

    async def _row_to_record(
        self,
        row: CaseApprovalRecordRow,
    ) -> CaseApprovalRecord:
        record = _row_to_record(row)
        if self._data_protection is None:
            return record
        guidance_ref = (
            await self._data_protection.decrypt_text(record.guidance_ref)
            if record.guidance_ref is not None
            else None
        )
        metadata = await self._data_protection.decrypt_json_values(
            dict(record.metadata)
        )
        return replace(
            record,
            guidance_ref=guidance_ref,
            metadata=metadata,
        )


def _apply_case_filters(
    stmt: Select[tuple[CaseApprovalRecordRow]],
    *,
    query: CaseApprovalQuery,
) -> Select[tuple[CaseApprovalRecordRow]]:
    if query.tenant_id is not None:
        stmt = stmt.where(CaseApprovalRecordRow.tenant_id == query.tenant_id)
    if query.session_id is not None:
        stmt = stmt.where(CaseApprovalRecordRow.session_id == UUID(query.session_id))
    if query.execution_id is not None:
        stmt = stmt.where(
            CaseApprovalRecordRow.execution_id == UUID(query.execution_id)
        )
    if query.dispatch_id is not None:
        stmt = stmt.where(CaseApprovalRecordRow.dispatch_id == UUID(query.dispatch_id))
    if query.resolution_proposal_id is not None:
        stmt = stmt.where(
            CaseApprovalRecordRow.resolution_proposal_id
            == UUID(query.resolution_proposal_id)
        )
    if query.status is not None:
        stmt = stmt.where(CaseApprovalRecordRow.status == query.status)
    if query.entry_category is not None:
        stmt = stmt.where(CaseApprovalRecordRow.entry_category == query.entry_category)
    return stmt


def _record_to_row(record: CaseApprovalRecord) -> CaseApprovalRecordRow:
    return CaseApprovalRecordRow(
        approval_case_id=UUID(record.approval_case_id),
        tenant_id=record.tenant_id,
        session_id=_optional_uuid(record.session_id),
        execution_id=_optional_uuid(record.execution_id),
        dispatch_id=_optional_uuid(record.dispatch_id),
        resolution_proposal_id=_optional_uuid(record.resolution_proposal_id),
        entry_category=record.entry_category.value,
        ticket_ref=record.ticket_ref,
        product=record.product,
        issue_summary=record.issue_summary,
        sme_recommendation_id=_optional_uuid(record.sme_recommendation_id),
        recommended_action=(
            dict(record.recommended_action)
            if record.recommended_action is not None
            else None
        ),
        status=record.status.value,
        guidance_round=record.guidance_round,
        guidance_ref=record.guidance_ref,
        governance_decision_id=_optional_uuid(record.governance_decision_id),
        requested_at=record.requested_at,
        resolved_at=record.resolved_at,
        resolved_by=record.resolved_by,
        resolution_note=record.resolution_note,
        dedup_key=record.dedup_key,
        metadata_json=dict(record.metadata),
    )


def _row_to_record(row: CaseApprovalRecordRow) -> CaseApprovalRecord:
    return CaseApprovalRecord(
        approval_case_id=str(row.approval_case_id),
        tenant_id=row.tenant_id,
        session_id=_optional_uuid_text(row.session_id),
        execution_id=_optional_uuid_text(row.execution_id),
        dispatch_id=_optional_uuid_text(row.dispatch_id),
        resolution_proposal_id=_optional_uuid_text(row.resolution_proposal_id),
        entry_category=CaseApprovalEntryCategory(row.entry_category),
        ticket_ref=row.ticket_ref,
        product=row.product,
        issue_summary=row.issue_summary,
        sme_recommendation_id=_optional_uuid_text(row.sme_recommendation_id),
        recommended_action=(
            _json_object(row.recommended_action)
            if row.recommended_action is not None
            else None
        ),
        status=CaseApprovalStatus(row.status),
        guidance_round=row.guidance_round,
        guidance_ref=row.guidance_ref,
        governance_decision_id=_optional_uuid_text(row.governance_decision_id),
        requested_at=row.requested_at,
        resolved_at=row.resolved_at,
        resolved_by=row.resolved_by,
        resolution_note=row.resolution_note,
        dedup_key=row.dedup_key,
        metadata=_json_object(row.metadata_json),
    )


def _outbox_record_to_row(
    record: CaseApprovalOutboxRecord,
) -> CaseApprovalOutboxRow:
    return CaseApprovalOutboxRow(
        outbox_id=UUID(record.outbox_id),
        approval_case_id=UUID(record.approval_case_id),
        tenant_id=record.tenant_id,
        status=record.status.value,
        created_at=record.created_at,
        claimed_at=record.claimed_at,
        published_at=record.published_at,
        publisher_id=record.publisher_id,
        claim_id=_optional_uuid(record.claim_id),
        republish_count=record.republish_count,
        dead_letter=record.dead_letter,
        last_error=record.last_error,
        metadata_json=dict(record.metadata),
    )


def _outbox_row_to_record(
    row: CaseApprovalOutboxRow,
) -> CaseApprovalOutboxRecord:
    return CaseApprovalOutboxRecord(
        outbox_id=str(row.outbox_id),
        approval_case_id=str(row.approval_case_id),
        tenant_id=row.tenant_id,
        status=CaseApprovalOutboxStatus(row.status),
        created_at=row.created_at,
        claimed_at=row.claimed_at,
        published_at=row.published_at,
        publisher_id=row.publisher_id,
        claim_id=_optional_uuid_text(row.claim_id),
        republish_count=row.republish_count,
        dead_letter=row.dead_letter,
        last_error=row.last_error,
        metadata=_json_object(row.metadata_json),
    )


def _optional_uuid(value: str | UUID | None) -> UUID | None:
    if value is None:
        return None
    return UUID(str(value))


def _optional_uuid_text(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def _json_object(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in cast(Mapping[Any, Any], value).items()}
    return {}


def _enforce_expected_tenant(tenant_id: str, expected_tenant_id: str) -> None:
    if tenant_id != expected_tenant_id:
        raise CaseApprovalPersistenceError("case approval tenant mismatch")


__all__ = ["PostgresCaseApprovalPersistence"]
