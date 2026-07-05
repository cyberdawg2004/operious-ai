"""Persistable QA score record shapes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


def _empty_metadata() -> dict[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class QAScoreRecord:
    """Durable QA score produced from one supervisor inspection.

    semantic_grounding (MVP-6): LLM-scored dimension measuring whether
    the cited KB text actually supports the claims in the reply. Defaults
    to 0.0 (absent / not yet scored). Populated by SemanticQAAgent post-
    resolution and stored in the semantic_grounding column (migration 0095).
    """

    score_id: str
    inspection_id: str
    execution_id: str
    tenant_id: str
    tenant_authority_source: str | None
    diagnostic_accuracy: float
    policy_compliance: float
    timeline_integrity: float
    resolution_quality: float
    overall_score: float
    supervisor_decision_kind: str
    finding_count: int
    evaluation_count: int
    escalation_count: int
    scored_at: str
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)
    # MVP-6: 0.0 = not yet scored or citations absent.
    semantic_grounding: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "score_id": self.score_id,
            "inspection_id": self.inspection_id,
            "execution_id": self.execution_id,
            "tenant_id": self.tenant_id,
            "tenant_authority_source": self.tenant_authority_source,
            "diagnostic_accuracy": self.diagnostic_accuracy,
            "policy_compliance": self.policy_compliance,
            "timeline_integrity": self.timeline_integrity,
            "resolution_quality": self.resolution_quality,
            "overall_score": self.overall_score,
            "supervisor_decision_kind": self.supervisor_decision_kind,
            "finding_count": self.finding_count,
            "evaluation_count": self.evaluation_count,
            "escalation_count": self.escalation_count,
            "scored_at": self.scored_at,
            "metadata": dict(self.metadata),
            "semantic_grounding": self.semantic_grounding,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "QAScoreRecord":
        return cls(
            score_id=str(data["score_id"]),
            inspection_id=str(data["inspection_id"]),
            execution_id=str(data["execution_id"]),
            tenant_id=str(data["tenant_id"]),
            tenant_authority_source=(
                str(data["tenant_authority_source"])
                if data.get("tenant_authority_source") is not None
                else None
            ),
            diagnostic_accuracy=float(data["diagnostic_accuracy"]),
            policy_compliance=float(data["policy_compliance"]),
            timeline_integrity=float(data["timeline_integrity"]),
            resolution_quality=float(data["resolution_quality"]),
            overall_score=float(data["overall_score"]),
            supervisor_decision_kind=str(data["supervisor_decision_kind"]),
            finding_count=int(data["finding_count"]),
            evaluation_count=int(data["evaluation_count"]),
            escalation_count=int(data["escalation_count"]),
            scored_at=str(data["scored_at"]),
            metadata=dict(data.get("metadata") or {}),
            semantic_grounding=float(data.get("semantic_grounding") or 0.0),
        )


__all__ = ["QAScoreRecord"]
