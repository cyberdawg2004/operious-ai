"""Persistable resolution proposal records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping
from uuid import UUID

from app.resolution.enums import (
    ResolutionAutonomyDecision,
    ResolutionGovernanceVerdict,
    ResolutionOutboundDraftStatus,
    ResolutionProposalStatus,
    ResolutionSupervisorVerdict,
)
from app.resolution.identity import (
    ResolutionOutboundDraftId,
    ResolutionProposalId,
)


def _empty_json_list() -> tuple[Mapping[str, Any], ...]:
    return ()


def _empty_json_mapping() -> Mapping[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class ResolutionProposalRecord:
    """Durable customer-safe response proposal."""

    proposal_id: ResolutionProposalId
    tenant_id: str
    session_id: str | None
    execution_id: str | None
    dispatch_id: str
    diagnostic_event_id: str | None
    proposed_customer_reply: str
    resolution_category: str
    confidence: float
    supervisor_verdict: ResolutionSupervisorVerdict
    governance_verdict: ResolutionGovernanceVerdict
    autonomy_decision: ResolutionAutonomyDecision
    status: ResolutionProposalStatus
    created_at: datetime
    updated_at: datetime
    governance_decision_id: UUID | None = None
    recommended_actions: tuple[Mapping[str, Any], ...] = field(
        default_factory=_empty_json_list
    )
    evidence: tuple[Mapping[str, Any], ...] = field(
        default_factory=_empty_json_list
    )
    source_language: str = "en"
    # JSONB metadata column (migration 0096). Stores gate_reasons (list of
    # strings from _evaluate_gate e.g. "fraud_risk_high") and future context.
    # Backward-compat: {} for pre-migration rows.
    metadata: Mapping[str, Any] = field(default_factory=_empty_json_mapping)

    def to_dict(self) -> dict[str, Any]:
        """Return the API/timeline-safe representation."""

        return {
            "proposal_id": str(self.proposal_id),
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "execution_id": self.execution_id,
            "dispatch_id": self.dispatch_id,
            "diagnostic_event_id": self.diagnostic_event_id,
            "proposed_customer_reply": self.proposed_customer_reply,
            "source_language": self.source_language,
            "resolution_category": self.resolution_category,
            "confidence": self.confidence,
            "recommended_actions": [
                dict(action) for action in self.recommended_actions
            ],
            "evidence": [dict(item) for item in self.evidence],
            "supervisor_verdict": self.supervisor_verdict.value,
            "governance_verdict": self.governance_verdict.value,
            "governance_decision_id": (
                str(self.governance_decision_id)
                if self.governance_decision_id is not None
                else None
            ),
            "autonomy_decision": self.autonomy_decision.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": dict(self.metadata),
        }


def resolution_proposal_gate_reasons(
    proposal: "ResolutionProposalRecord",
) -> tuple[str, ...]:
    """Extract gate reasons from a proposal's metadata (e.g. 'fraud_risk_high')."""
    raw = proposal.metadata.get("gate_reasons")
    if not isinstance(raw, list):
        return ()
    return tuple(str(r) for r in raw if isinstance(r, str))


@dataclass(frozen=True, slots=True)
class ResolutionOutboundDraftRecord:
    """Durable no-send customer reply draft derived from a proposal."""

    draft_id: ResolutionOutboundDraftId
    tenant_id: str
    proposal_id: ResolutionProposalId
    session_id: str
    execution_id: str
    dispatch_id: str
    diagnostic_event_id: str | None
    governance_decision_id: UUID | None
    status: ResolutionOutboundDraftStatus
    draft_body: str
    draft_body_sha256: str
    resolution_category: str
    confidence: float
    created_at: datetime
    updated_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=_empty_json_mapping)

    def to_dict(self) -> dict[str, Any]:
        """Return the API/timeline-safe draft representation."""

        return {
            "draft_id": str(self.draft_id),
            "tenant_id": self.tenant_id,
            "proposal_id": str(self.proposal_id),
            "session_id": self.session_id,
            "execution_id": self.execution_id,
            "dispatch_id": self.dispatch_id,
            "diagnostic_event_id": self.diagnostic_event_id,
            "governance_decision_id": (
                str(self.governance_decision_id)
                if self.governance_decision_id is not None
                else None
            ),
            "status": self.status.value,
            "draft_body": self.draft_body,
            "draft_body_sha256": self.draft_body_sha256,
            "metadata": dict(self.metadata),
            "resolution_category": self.resolution_category,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


__all__ = ["ResolutionOutboundDraftRecord", "ResolutionProposalRecord"]
