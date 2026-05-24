"""Persistable escalation record shapes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.escalation.enums import EscalationOutboxStatus


def _empty_metadata() -> dict[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class EscalationRecord:
    """Durable human approval queue record for a governance denial."""

    escalation_id: str
    session_id: str
    tenant_id: str
    reason: str
    governance_decision_id: str
    status: str
    created_at: str
    resolved_at: str | None = None
    resolution: str | None = None
    resolved_by: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "escalation_id": self.escalation_id,
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "reason": self.reason,
            "governance_decision_id": self.governance_decision_id,
            "status": self.status,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "resolution": self.resolution,
            "resolved_by": self.resolved_by,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EscalationRecord":
        return cls(
            escalation_id=str(data["escalation_id"]),
            session_id=str(data["session_id"]),
            tenant_id=str(data["tenant_id"]),
            reason=str(data["reason"]),
            governance_decision_id=str(data["governance_decision_id"]),
            status=str(data["status"]),
            created_at=str(data["created_at"]),
            resolved_at=(
                str(data["resolved_at"])
                if data.get("resolved_at") is not None
                else None
            ),
            resolution=(
                str(data["resolution"])
                if data.get("resolution") is not None
                else None
            ),
            resolved_by=(
                str(data["resolved_by"])
                if data.get("resolved_by") is not None
                else None
            ),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class EscalationOutboxRecord:
    """Durable publication row for one escalation intent."""

    outbox_id: str
    escalation_id: str
    tenant_id: str
    status: EscalationOutboxStatus
    created_at: datetime
    claimed_at: datetime | None = None
    published_at: datetime | None = None
    publisher_id: str | None = None
    claim_id: str | None = None
    republish_count: int = 0
    dead_letter: bool = False
    last_error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)


__all__ = ["EscalationOutboxRecord", "EscalationRecord"]
