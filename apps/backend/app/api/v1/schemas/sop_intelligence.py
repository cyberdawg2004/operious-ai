"""Transport schemas for SOP intelligence approval proposals."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.sop_intelligence.enums import ApprovalStatus
from app.sop_intelligence.persistence import ApprovalRecord


class ApprovalRecordResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    approval_id: str
    tenant_id: str
    document_id: str
    proposed_change: str
    evidence_sessions: list[str]
    confidence: float
    status: ApprovalStatus
    proposed_by: str
    reviewed_by: str | None = None
    created_at: str
    metadata: dict[str, Any]

    @classmethod
    def from_record(
        cls,
        record: ApprovalRecord,
    ) -> "ApprovalRecordResponse":
        return cls(
            approval_id=record.approval_id,
            tenant_id=record.tenant_id,
            document_id=record.document_id,
            proposed_change=record.proposed_change,
            evidence_sessions=list(record.evidence_sessions),
            confidence=record.confidence,
            status=ApprovalStatus(record.status),
            proposed_by=record.proposed_by,
            reviewed_by=record.reviewed_by,
            created_at=record.created_at,
            metadata=dict(record.metadata),
        )


def _empty_approval_items() -> list[ApprovalRecordResponse]:
    return []


class ApprovalRecordPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[ApprovalRecordResponse] = Field(
        default_factory=_empty_approval_items
    )
    total: int
    offset: int


__all__ = [
    "ApprovalRecordPage",
    "ApprovalRecordResponse",
]
