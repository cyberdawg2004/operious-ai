"""Transport contracts for manager action approvals."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agents.tools.approvals import ActionApprovalRecord
from app.services.action_approval_service import ActionApprovalWithContext


class ApproveActionApprovalRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    note: str | None = None


class DenyActionApprovalRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    reason: str = Field(min_length=1)


class ActionApprovalSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    approval_id: str
    tenant_id: str
    session_id: str
    execution_id: str | None
    status: str
    tool_name: str
    payload: dict[str, Any]
    idempotency_key: str
    governance_decision_id: str | None
    requested_at: datetime
    resolved_at: datetime | None
    resolved_by: str | None
    resolution_note: str | None
    metadata: dict[str, Any]

    @classmethod
    def from_record(
        cls,
        record: ActionApprovalRecord,
    ) -> "ActionApprovalSummaryResponse":
        return cls(
            approval_id=record.approval_id,
            tenant_id=record.tenant_id,
            session_id=record.session_id,
            execution_id=record.execution_id,
            status=record.status,
            tool_name=record.tool_name,
            payload=dict(record.payload_json),
            idempotency_key=record.idempotency_key,
            governance_decision_id=record.governance_decision_id,
            requested_at=record.requested_at,
            resolved_at=record.resolved_at,
            resolved_by=record.resolved_by,
            resolution_note=record.resolution_note,
            metadata=dict(record.metadata),
        )


def _empty_action_approval_items() -> list[ActionApprovalSummaryResponse]:
    return []


class ActionApprovalListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[ActionApprovalSummaryResponse] = Field(
        default_factory=_empty_action_approval_items
    )


class ActionApprovalDetailResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    approval_id: str
    status: str
    tool_name: str
    payload: dict[str, Any]
    idempotency_key: str
    requested_at: datetime
    session_id: str
    session_phase: str
    session_opened_at: datetime
    classification_category: str | None
    classification_confidence: float | None
    classification_summary: str | None
    governance_decision_id: str | None
    governance_reason: str | None
    governance_evaluated_at: datetime | None

    @classmethod
    def from_context(
        cls,
        context: ActionApprovalWithContext,
    ) -> "ActionApprovalDetailResponse":
        return cls(
            approval_id=context.approval_id,
            status=context.status,
            tool_name=context.tool_name,
            payload=dict(context.payload),
            idempotency_key=context.idempotency_key,
            requested_at=context.requested_at,
            session_id=context.session_id,
            session_phase=context.session_phase,
            session_opened_at=context.session_opened_at,
            classification_category=context.classification_category,
            classification_confidence=context.classification_confidence,
            classification_summary=context.classification_summary,
            governance_decision_id=context.governance_decision_id,
            governance_reason=context.governance_reason,
            governance_evaluated_at=context.governance_evaluated_at,
        )


__all__ = [
    "ActionApprovalDetailResponse",
    "ActionApprovalListResponse",
    "ActionApprovalSummaryResponse",
    "ApproveActionApprovalRequest",
    "DenyActionApprovalRequest",
]
