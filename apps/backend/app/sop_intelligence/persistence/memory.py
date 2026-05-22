"""In-memory SOP intelligence approval persistence."""

from __future__ import annotations

import asyncio

from app.sop_intelligence.exceptions import (
    SOPIntelligencePersistenceError,
)
from app.sop_intelligence.persistence.models import (
    ApprovalPage,
    ApprovalQuery,
)
from app.sop_intelligence.persistence.records import ApprovalRecord


class InMemorySOPApprovalPersistence:
    """Reference approval proposal store."""

    def __init__(self) -> None:
        self._records: dict[str, ApprovalRecord] = {}
        self._lock = asyncio.Lock()

    async def create_approval_record(
        self,
        record: ApprovalRecord,
        *,
        expected_tenant_id: str,
    ) -> None:
        _enforce_expected_tenant(record.tenant_id, expected_tenant_id)
        async with self._lock:
            if record.approval_id in self._records:
                raise SOPIntelligencePersistenceError(
                    f"approval {record.approval_id!r} already recorded"
                )
            self._records[record.approval_id] = record

    async def update_approval_record(
        self,
        record: ApprovalRecord,
        *,
        expected_tenant_id: str,
    ) -> None:
        _enforce_expected_tenant(record.tenant_id, expected_tenant_id)
        async with self._lock:
            existing = self._records.get(record.approval_id)
            if existing is None or existing.tenant_id != expected_tenant_id:
                raise SOPIntelligencePersistenceError(
                    f"approval {record.approval_id!r} not found"
                )
            self._records[record.approval_id] = record

    async def get_approval_record(
        self,
        approval_id: str,
        *,
        expected_tenant_id: str,
    ) -> ApprovalRecord | None:
        record = self._records.get(approval_id)
        if record is None or record.tenant_id != expected_tenant_id:
            return None
        return record

    async def list_approval_records(
        self,
        query: ApprovalQuery,
        *,
        expected_tenant_id: str,
    ) -> ApprovalPage:
        rows = [
            record
            for record in self._records.values()
            if _matches(
                record,
                query=query,
                expected_tenant_id=expected_tenant_id,
            )
        ]
        rows.sort(key=lambda r: (r.created_at, r.approval_id))
        total = len(rows)
        page = rows[query.offset : query.offset + query.limit]
        return ApprovalPage(items=tuple(page), total=total, offset=query.offset)


def _matches(
    record: ApprovalRecord,
    *,
    query: ApprovalQuery,
    expected_tenant_id: str,
) -> bool:
    if record.tenant_id != expected_tenant_id:
        return False
    if query.approval_id is not None and record.approval_id != query.approval_id:
        return False
    if query.tenant_id is not None and record.tenant_id != query.tenant_id:
        return False
    if query.document_id is not None and record.document_id != query.document_id:
        return False
    if query.status is not None and record.status != query.status:
        return False
    if query.min_confidence is not None and record.confidence < query.min_confidence:
        return False
    return True


def _enforce_expected_tenant(
    tenant_id: str,
    expected_tenant_id: str,
) -> None:
    if tenant_id != expected_tenant_id:
        raise SOPIntelligencePersistenceError(
            "approval tenant_id does not match expected_tenant_id"
        )


__all__ = ["InMemorySOPApprovalPersistence"]
