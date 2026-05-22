"""Storage contract for SOP intelligence approval proposals."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.sop_intelligence.persistence.models import (
    ApprovalPage,
    ApprovalQuery,
)
from app.sop_intelligence.persistence.records import ApprovalRecord


@runtime_checkable
class SOPApprovalPersistenceProtocol(Protocol):
    """Tenant-scoped write-once approval proposal persistence."""

    async def create_approval_record(
        self,
        record: ApprovalRecord,
        *,
        expected_tenant_id: str,
    ) -> None: ...

    async def get_approval_record(
        self,
        approval_id: str,
        *,
        expected_tenant_id: str,
    ) -> ApprovalRecord | None: ...

    async def list_approval_records(
        self,
        query: ApprovalQuery,
        *,
        expected_tenant_id: str,
    ) -> ApprovalPage: ...


__all__ = ["SOPApprovalPersistenceProtocol"]
