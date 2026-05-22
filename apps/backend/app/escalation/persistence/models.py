"""Escalation persistence query/page value objects."""

from __future__ import annotations

from dataclasses import dataclass

from app.escalation.persistence.records import EscalationRecord


@dataclass(frozen=True, slots=True)
class EscalationQuery:
    escalation_id: str | None = None
    session_id: str | None = None
    governance_decision_id: str | None = None
    tenant_id: str | None = None
    status: str | None = None
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("EscalationQuery.limit must be >= 1")
        if self.offset < 0:
            raise ValueError("EscalationQuery.offset must be >= 0")


@dataclass(frozen=True, slots=True)
class EscalationPage:
    items: tuple[EscalationRecord, ...]
    total: int
    offset: int = 0


__all__ = ["EscalationPage", "EscalationQuery"]
