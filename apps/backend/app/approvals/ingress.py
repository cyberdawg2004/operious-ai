"""Thin producer ingress for SME-reviewed approval cases."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.approvals.enums import CaseApprovalEntryCategory, CaseApprovalStatus
from app.approvals.identity import (
    derive_approval_case_id,
    derive_approval_dedup_key,
)
from app.approvals.persistence import (
    CaseApprovalPersistenceProtocol,
    CaseApprovalRecord,
)
from app.approvals.publisher import CaseApprovalReviewPublisher


@dataclass(frozen=True, slots=True)
class CaseApprovalReviewRequest:
    tenant_id: str
    entry_category: CaseApprovalEntryCategory
    session_id: str | None = None
    execution_id: str | None = None
    dispatch_id: str | None = None
    resolution_proposal_id: str | None = None
    ticket_ref: str | None = None
    product: str | None = None
    issue_summary: str | None = None
    recommended_action: Mapping[str, Any] | None = None
    metadata: Mapping[str, Any] | None = None


class ApprovalQueueIngressService:
    """Boundary producers call to request SME review."""

    def __init__(
        self,
        *,
        persistence: CaseApprovalPersistenceProtocol,
        publisher: CaseApprovalReviewPublisher | None = None,
    ) -> None:
        self._persistence = persistence
        self._publisher = publisher

    async def request_case_review(
        self,
        request: CaseApprovalReviewRequest,
        *,
        expected_tenant_id: str,
    ) -> CaseApprovalRecord:
        if request.tenant_id != expected_tenant_id:
            raise ValueError("approval ingress tenant mismatch")
        dedup_key = derive_approval_dedup_key(
            tenant_id=request.tenant_id,
            execution_id=request.execution_id,
            dispatch_id=request.dispatch_id,
            session_id=request.session_id,
            entry_category=request.entry_category.value,
        )
        approval_case_id = str(
            derive_approval_case_id(
                tenant_id=request.tenant_id,
                dedup_key=dedup_key,
            )
        )
        record = CaseApprovalRecord(
            approval_case_id=approval_case_id,
            tenant_id=request.tenant_id,
            session_id=request.session_id,
            execution_id=request.execution_id,
            dispatch_id=request.dispatch_id,
            resolution_proposal_id=request.resolution_proposal_id,
            entry_category=request.entry_category,
            ticket_ref=request.ticket_ref,
            product=request.product,
            issue_summary=request.issue_summary,
            recommended_action=(
                dict(request.recommended_action)
                if request.recommended_action is not None
                else None
            ),
            status=CaseApprovalStatus.PENDING_SME_REVIEW,
            requested_at=datetime.now(timezone.utc),
            dedup_key=dedup_key,
            metadata={
                **dict(request.metadata or {}),
                "proposal_only_sme": True,
            },
        )
        created = await self._persistence.create_case(
            record,
            expected_tenant_id=expected_tenant_id,
        )
        if (
            self._publisher is not None
            and created.status is CaseApprovalStatus.PENDING_SME_REVIEW
        ):
            await self._publisher.publish_case_review(
                approval_case_id=created.approval_case_id,
                tenant_id=created.tenant_id,
            )
        return created


__all__ = [
    "ApprovalQueueIngressService",
    "CaseApprovalReviewRequest",
]
