"""Transport contracts for SME-reviewed approval cases."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.approvals.enums import CaseApprovalEntryCategory, CaseApprovalStatus
from app.approvals.persistence import CaseApprovalRecord


class CaseApprovalApproveRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    note: str | None = None


class CaseApprovalGuideRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    guidance: str = Field(min_length=1, max_length=4000)


class CaseApprovalEscalateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    reason: str = Field(min_length=1, max_length=4000)


class CaseApprovalRejectRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    reason: str | None = Field(default=None, max_length=4000)


class CaseApprovalResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    approval_case_id: str
    tenant_id: str
    session_id: str | None
    execution_id: str | None
    dispatch_id: str | None
    resolution_proposal_id: str | None
    entry_category: CaseApprovalEntryCategory
    ticket_ref: str | None
    product: str | None
    issue_summary: str | None
    sme_recommendation_id: str | None
    recommended_action: dict[str, Any] | None
    status: CaseApprovalStatus
    guidance_round: int
    governance_decision_id: str | None
    requested_at: datetime
    resolved_at: datetime | None
    resolved_by: str | None
    resolution_note: str | None
    metadata: dict[str, Any]

    @classmethod
    def from_record(cls, record: CaseApprovalRecord) -> "CaseApprovalResponse":
        return cls(
            approval_case_id=record.approval_case_id,
            tenant_id=record.tenant_id,
            session_id=record.session_id,
            execution_id=record.execution_id,
            dispatch_id=record.dispatch_id,
            resolution_proposal_id=record.resolution_proposal_id,
            entry_category=record.entry_category,
            ticket_ref=record.ticket_ref,
            product=record.product,
            issue_summary=record.issue_summary,
            sme_recommendation_id=record.sme_recommendation_id,
            recommended_action=(
                dict(record.recommended_action)
                if record.recommended_action is not None
                else None
            ),
            status=record.status,
            guidance_round=record.guidance_round,
            governance_decision_id=record.governance_decision_id,
            requested_at=record.requested_at,
            resolved_at=record.resolved_at,
            resolved_by=record.resolved_by,
            resolution_note=record.resolution_note,
            metadata=dict(record.metadata),
        )


def _empty_case_items() -> list[CaseApprovalResponse]:
    return []


class CaseApprovalListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[CaseApprovalResponse] = Field(default_factory=_empty_case_items)


__all__ = [
    "CaseApprovalApproveRequest",
    "CaseApprovalEscalateRequest",
    "CaseApprovalGuideRequest",
    "CaseApprovalListResponse",
    "CaseApprovalRejectRequest",
    "CaseApprovalResponse",
]
