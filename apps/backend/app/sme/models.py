"""Structured SME review models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence


def _empty_mapping() -> dict[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class SmeCaseContext:
    """Evidence passed into the SME reviewer."""

    approval_case_id: str
    tenant_id: str
    entry_category: str
    session_id: str | None = None
    execution_id: str | None = None
    dispatch_id: str | None = None
    resolution_proposal_id: str | None = None
    ticket_ref: str | None = None
    product: str | None = None
    issue_summary: str | None = None
    proposed_customer_reply: str | None = None
    recommended_actions: Sequence[Mapping[str, Any]] = ()
    citations: Sequence[Mapping[str, Any]] = ()
    timeline: Sequence[Mapping[str, Any]] = ()
    metadata: Mapping[str, Any] = field(default_factory=_empty_mapping)


@dataclass(frozen=True, slots=True)
class SmeRecommendation:
    """Proposal-only SME recommendation for human approval."""

    recommendation_id: str
    recommended_reply: str
    recommended_actions: tuple[Mapping[str, Any], ...]
    rationale: str
    confidence: float
    citations: tuple[Mapping[str, Any], ...]
    risk_flags: tuple[str, ...]
    created_at: datetime
    reply_segments: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=_empty_mapping)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "recommended_reply": self.recommended_reply,
            "recommended_actions": [
                dict(action) for action in self.recommended_actions
            ],
            "rationale": self.rationale,
            "confidence": self.confidence,
            "citations": [dict(citation) for citation in self.citations],
            "risk_flags": list(self.risk_flags),
            "reply_segments": [dict(segment) for segment in self.reply_segments],
            "created_at": self.created_at.isoformat(),
            "metadata": dict(self.metadata),
        }


__all__ = ["SmeCaseContext", "SmeRecommendation"]
