"""Transport contracts for escalation queue endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.escalation.enums import (
    EscalationHandoffKind,
    EscalationPriority,
    EscalationStatus,
)
from app.escalation.persistence import EscalationRecord


class EscalationResolutionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    resolution: str = Field(min_length=1)


class EscalationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    escalation_id: str
    session_id: str
    tenant_id: str
    reason: str
    governance_decision_id: str
    status: EscalationStatus
    handoff_kind: EscalationHandoffKind
    priority: EscalationPriority
    created_at: str
    resolved_at: str | None = None
    resolution: str | None = None
    resolved_by: str | None = None
    governance_override_decision_id: str | None = None
    source_decision: str | None = None

    @classmethod
    def from_record(cls, record: EscalationRecord) -> "EscalationResponse":
        override_id = record.metadata.get("governance_override_decision_id")
        source_decision = record.metadata.get("source_decision")
        return cls(
            escalation_id=record.escalation_id,
            session_id=record.session_id,
            tenant_id=record.tenant_id,
            reason=record.reason,
            governance_decision_id=record.governance_decision_id,
            status=EscalationStatus(record.status),
            handoff_kind=EscalationHandoffKind(record.handoff_kind),
            priority=EscalationPriority(record.priority),
            created_at=record.created_at,
            resolved_at=record.resolved_at,
            resolution=record.resolution,
            resolved_by=record.resolved_by,
            governance_override_decision_id=(
                str(override_id) if override_id is not None else None
            ),
            source_decision=(
                str(source_decision) if source_decision is not None else None
            ),
        )


def _empty_escalation_items() -> list[EscalationResponse]:
    return []


class EscalationPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[EscalationResponse] = Field(
        default_factory=_empty_escalation_items
    )
    total: int
    offset: int


__all__ = [
    "EscalationPage",
    "EscalationResolutionRequest",
    "EscalationResponse",
]
