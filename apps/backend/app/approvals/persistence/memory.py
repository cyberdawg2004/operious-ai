"""In-memory case approval persistence."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime

from app.approvals.enums import CaseApprovalOutboxStatus
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


class InMemoryCaseApprovalPersistence:
    """Reference tenant-scoped approval store."""

    def __init__(self) -> None:
        self._cases: dict[str, CaseApprovalRecord] = {}
        self._dedup: dict[tuple[str, str], str] = {}
        self._outbox_by_id: dict[str, CaseApprovalOutboxRecord] = {}
        self._outbox_by_case: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def create_case(
        self,
        record: CaseApprovalRecord,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalRecord:
        _assert_tenant(record.tenant_id, expected_tenant_id)
        async with self._lock:
            dedup_key = (record.tenant_id, record.dedup_key)
            existing_id = self._dedup.get(dedup_key)
            if existing_id is not None:
                return self._cases[existing_id]
            self._cases[record.approval_case_id] = record
            self._dedup[dedup_key] = record.approval_case_id
            return record

    async def update_case(
        self,
        record: CaseApprovalRecord,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalRecord:
        _assert_tenant(record.tenant_id, expected_tenant_id)
        async with self._lock:
            current = self._cases.get(record.approval_case_id)
            if current is None or current.tenant_id != expected_tenant_id:
                raise CaseApprovalPersistenceError(
                    f"unknown approval case {record.approval_case_id!r}"
                )
            self._cases[record.approval_case_id] = record
            self._dedup[(record.tenant_id, record.dedup_key)] = (
                record.approval_case_id
            )
            return record

    async def get_case(
        self,
        approval_case_id: str,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalRecord | None:
        record = self._cases.get(approval_case_id)
        if record is None or record.tenant_id != expected_tenant_id:
            return None
        return record

    async def get_case_by_dedup_key(
        self,
        dedup_key: str,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalRecord | None:
        approval_case_id = self._dedup.get((expected_tenant_id, dedup_key))
        if approval_case_id is None:
            return None
        return await self.get_case(
            approval_case_id,
            expected_tenant_id=expected_tenant_id,
        )

    async def list_cases(
        self,
        query: CaseApprovalQuery,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalPage:
        rows = [
            record
            for record in self._cases.values()
            if _matches_case(record, query=query, expected_tenant_id=expected_tenant_id)
        ]
        rows.sort(key=lambda item: (item.requested_at, item.approval_case_id))
        rows.reverse()
        return CaseApprovalPage(
            items=tuple(rows[query.offset : query.offset + query.limit]),
            total=len(rows),
            limit=query.limit,
            offset=query.offset,
        )

    async def save_outbox(
        self,
        record: CaseApprovalOutboxRecord,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalOutboxRecord:
        _assert_tenant(record.tenant_id, expected_tenant_id)
        async with self._lock:
            existing_id = self._outbox_by_case.get(record.approval_case_id)
            if existing_id is not None:
                return self._outbox_by_id[existing_id]
            self._outbox_by_id[record.outbox_id] = record
            self._outbox_by_case[record.approval_case_id] = record.outbox_id
            return record

    async def get_outbox_by_case(
        self,
        approval_case_id: str,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalOutboxRecord | None:
        outbox_id = self._outbox_by_case.get(approval_case_id)
        if outbox_id is None:
            return None
        record = self._outbox_by_id.get(outbox_id)
        if record is None or record.tenant_id != expected_tenant_id:
            return None
        return record

    async def republish_outbox(
        self,
        record: CaseApprovalOutboxRecord,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalOutboxRecord:
        if record.tenant_id != expected_tenant_id:
            raise CaseApprovalPersistenceError("case approval tenant mismatch")
        async with self._lock:
            existing_id = self._outbox_by_case.get(record.approval_case_id)
            if existing_id is None:
                self._outbox_by_id[record.outbox_id] = record
                self._outbox_by_case[record.approval_case_id] = record.outbox_id
                return record
            existing = self._outbox_by_id[existing_id]
            updated = replace(
                existing,
                status=CaseApprovalOutboxStatus.PENDING,
                claimed_at=None,
                published_at=None,
                publisher_id=None,
                claim_id=None,
                dead_letter=False,
                last_error=None,
                metadata=dict(record.metadata),
            )
            self._outbox_by_id[existing_id] = updated
            return updated

    async def claim_outbox(
        self,
        *,
        approval_case_id: str,
        publisher_id: str,
        claim_id: str,
        claimed_at: datetime,
        expected_tenant_id: str,
    ) -> CaseApprovalOutboxRecord | None:
        async with self._lock:
            record = await self.get_outbox_by_case(
                approval_case_id,
                expected_tenant_id=expected_tenant_id,
            )
            if record is None or record.status is not CaseApprovalOutboxStatus.PENDING:
                return None
            updated = replace(
                record,
                status=CaseApprovalOutboxStatus.PUBLISHING,
                claimed_at=claimed_at,
                publisher_id=publisher_id,
                claim_id=claim_id,
                republish_count=record.republish_count + 1,
                last_error=None,
            )
            self._outbox_by_id[updated.outbox_id] = updated
            return updated

    async def mark_outbox_published(
        self,
        *,
        outbox_id: str,
        claim_id: str,
        published_at: datetime,
        expected_tenant_id: str,
    ) -> CaseApprovalOutboxRecord:
        return await self._mark_outbox_terminal(
            outbox_id=outbox_id,
            claim_id=claim_id,
            status=CaseApprovalOutboxStatus.PUBLISHED,
            expected_tenant_id=expected_tenant_id,
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
        return await self._mark_outbox_terminal(
            outbox_id=outbox_id,
            claim_id=claim_id,
            status=CaseApprovalOutboxStatus.FAILED,
            expected_tenant_id=expected_tenant_id,
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
        rows = [
            record
            for record in self._outbox_by_id.values()
            if _matches_outbox(
                record,
                query=query,
                expected_tenant_id=expected_tenant_id,
            )
        ]
        rows.sort(key=lambda item: (item.created_at, item.outbox_id))
        return CaseApprovalOutboxPage(
            items=tuple(rows[query.offset : query.offset + query.limit]),
            total=len(rows),
            limit=query.limit,
            offset=query.offset,
        )

    async def _mark_outbox_terminal(
        self,
        *,
        outbox_id: str,
        claim_id: str,
        status: CaseApprovalOutboxStatus,
        expected_tenant_id: str,
        published_at: datetime | None,
        error: str | None,
        dead_letter: bool,
        failed_at: datetime | None = None,
    ) -> CaseApprovalOutboxRecord:
        async with self._lock:
            record = self._outbox_by_id.get(outbox_id)
            if record is None or record.tenant_id != expected_tenant_id:
                raise CaseApprovalPersistenceError(
                    f"unknown approval outbox {outbox_id!r}"
                )
            if record.claim_id != claim_id:
                raise CaseApprovalPersistenceError(
                    "approval outbox claim does not match"
                )
            metadata = dict(record.metadata)
            if failed_at is not None:
                metadata["failed_at"] = failed_at.isoformat()
            updated = replace(
                record,
                status=status,
                published_at=published_at,
                dead_letter=dead_letter,
                last_error=error,
                metadata=metadata,
            )
            self._outbox_by_id[outbox_id] = updated
            return updated


def _matches_case(
    record: CaseApprovalRecord,
    *,
    query: CaseApprovalQuery,
    expected_tenant_id: str,
) -> bool:
    if record.tenant_id != expected_tenant_id:
        return False
    if query.tenant_id is not None and record.tenant_id != query.tenant_id:
        return False
    if query.session_id is not None and record.session_id != query.session_id:
        return False
    if query.execution_id is not None and record.execution_id != query.execution_id:
        return False
    if query.dispatch_id is not None and record.dispatch_id != query.dispatch_id:
        return False
    if (
        query.resolution_proposal_id is not None
        and record.resolution_proposal_id != query.resolution_proposal_id
    ):
        return False
    if query.status is not None and record.status.value != query.status:
        return False
    if (
        query.entry_category is not None
        and record.entry_category.value != query.entry_category
    ):
        return False
    return True


def _matches_outbox(
    record: CaseApprovalOutboxRecord,
    *,
    query: CaseApprovalOutboxQuery,
    expected_tenant_id: str | None,
) -> bool:
    if expected_tenant_id is not None and record.tenant_id != expected_tenant_id:
        return False
    if query.tenant_id is not None and record.tenant_id != query.tenant_id:
        return False
    if query.status is not None and record.status.value != query.status:
        return False
    if query.dead_letter is not None and record.dead_letter != query.dead_letter:
        return False
    return True


def _assert_tenant(tenant_id: str, expected_tenant_id: str) -> None:
    if tenant_id != expected_tenant_id:
        raise CaseApprovalPersistenceError("case approval tenant mismatch")


__all__ = ["InMemoryCaseApprovalPersistence"]
