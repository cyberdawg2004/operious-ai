"""Persistable case approval record shapes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.approvals.enums import (
    CaseApprovalEntryCategory,
    CaseApprovalOutboxStatus,
    CaseApprovalStatus,
)


def _empty_metadata() -> dict[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class CaseApprovalRecord:
    """Durable SME-reviewed approval queue record."""

    approval_case_id: str
    tenant_id: str
    session_id: str | None
    execution_id: str | None
    dispatch_id: str | None
    entry_category: CaseApprovalEntryCategory
    status: CaseApprovalStatus
    requested_at: datetime
    dedup_key: str
    resolution_proposal_id: str | None = None
    ticket_ref: str | None = None
    product: str | None = None
    issue_summary: str | None = None
    sme_recommendation_id: str | None = None
    recommended_action: Mapping[str, Any] | None = None
    guidance_round: int = 0
    guidance_ref: str | None = None
    governance_decision_id: str | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution_note: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_case_id": self.approval_case_id,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "execution_id": self.execution_id,
            "dispatch_id": self.dispatch_id,
            "resolution_proposal_id": self.resolution_proposal_id,
            "entry_category": self.entry_category.value,
            "ticket_ref": self.ticket_ref,
            "product": self.product,
            "issue_summary": self.issue_summary,
            "sme_recommendation_id": self.sme_recommendation_id,
            "recommended_action": (
                dict(self.recommended_action)
                if self.recommended_action is not None
                else None
            ),
            "status": self.status.value,
            "guidance_round": self.guidance_round,
            "guidance_ref": self.guidance_ref,
            "governance_decision_id": self.governance_decision_id,
            "requested_at": self.requested_at.isoformat(),
            "resolved_at": (
                self.resolved_at.isoformat()
                if self.resolved_at is not None
                else None
            ),
            "resolved_by": self.resolved_by,
            "resolution_note": self.resolution_note,
            "dedup_key": self.dedup_key,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class CaseApprovalOutboxRecord:
    """Durable publication row for one approval queue event."""

    outbox_id: str
    approval_case_id: str
    tenant_id: str
    status: CaseApprovalOutboxStatus
    created_at: datetime
    claimed_at: datetime | None = None
    published_at: datetime | None = None
    publisher_id: str | None = None
    claim_id: str | None = None
    republish_count: int = 0
    dead_letter: bool = False
    last_error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)


__all__ = ["CaseApprovalOutboxRecord", "CaseApprovalRecord"]
