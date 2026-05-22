"""Persistable SOP intelligence approval proposal records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


def _empty_metadata() -> dict[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    """Durable proposal awaiting human review in Cognition Hub."""

    approval_id: str
    tenant_id: str
    document_id: str
    proposed_change: str
    evidence_sessions: tuple[str, ...]
    confidence: float
    status: str
    proposed_by: str
    created_at: str
    reviewed_by: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "tenant_id": self.tenant_id,
            "document_id": self.document_id,
            "proposed_change": self.proposed_change,
            "evidence_sessions": list(self.evidence_sessions),
            "confidence": self.confidence,
            "status": self.status,
            "proposed_by": self.proposed_by,
            "reviewed_by": self.reviewed_by,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ApprovalRecord":
        return cls(
            approval_id=str(data["approval_id"]),
            tenant_id=str(data["tenant_id"]),
            document_id=str(data["document_id"]),
            proposed_change=str(data["proposed_change"]),
            evidence_sessions=tuple(
                str(value)
                for value in (data.get("evidence_sessions") or ())
            ),
            confidence=float(data["confidence"]),
            status=str(data["status"]),
            proposed_by=str(data["proposed_by"]),
            reviewed_by=(
                str(data["reviewed_by"])
                if data.get("reviewed_by") is not None
                else None
            ),
            created_at=str(data["created_at"]),
            metadata=dict(data.get("metadata") or {}),
        )


__all__ = ["ApprovalRecord"]
