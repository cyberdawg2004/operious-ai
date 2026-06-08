"""Storage contract for case approvals."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

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


@runtime_checkable
class CaseApprovalPersistenceProtocol(Protocol):
    async def create_case(
        self,
        record: CaseApprovalRecord,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalRecord: ...

    async def update_case(
        self,
        record: CaseApprovalRecord,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalRecord: ...

    async def get_case(
        self,
        approval_case_id: str,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalRecord | None: ...

    async def get_case_by_dedup_key(
        self,
        dedup_key: str,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalRecord | None: ...

    async def list_cases(
        self,
        query: CaseApprovalQuery,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalPage: ...

    async def save_outbox(
        self,
        record: CaseApprovalOutboxRecord,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalOutboxRecord: ...

    async def get_outbox_by_case(
        self,
        approval_case_id: str,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalOutboxRecord | None: ...

    async def republish_outbox(
        self,
        record: CaseApprovalOutboxRecord,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalOutboxRecord:
        """Create or reset the case outbox row to PENDING.

        Used when a guided re-review produces a revised recommendation
        that the operator queue must be re-notified about.
        """
        ...

    async def claim_outbox(
        self,
        *,
        approval_case_id: str,
        publisher_id: str,
        claim_id: str,
        claimed_at: datetime,
        expected_tenant_id: str,
    ) -> CaseApprovalOutboxRecord | None: ...

    async def mark_outbox_published(
        self,
        *,
        outbox_id: str,
        claim_id: str,
        published_at: datetime,
        expected_tenant_id: str,
    ) -> CaseApprovalOutboxRecord: ...

    async def mark_outbox_failed(
        self,
        *,
        outbox_id: str,
        claim_id: str,
        error: str,
        failed_at: datetime,
        dead_letter: bool,
        expected_tenant_id: str,
    ) -> CaseApprovalOutboxRecord: ...

    async def list_outbox(
        self,
        query: CaseApprovalOutboxQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> CaseApprovalOutboxPage: ...


__all__ = ["CaseApprovalPersistenceProtocol"]
