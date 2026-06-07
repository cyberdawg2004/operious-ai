"""Escalation substrate enums."""

from __future__ import annotations

from enum import StrEnum


class EscalationStatus(StrEnum):
    """Human approval queue lifecycle states."""

    PENDING = "pending"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"


class EscalationHandoffKind(StrEnum):
    """Why an operator-visible escalation record exists."""

    DENIAL = "denial"
    ESCALATION = "escalation"
    CRISIS = "crisis"


class EscalationPriority(StrEnum):
    """Operator queue priority for sorting and visual treatment."""

    NORMAL = "normal"
    HIGH = "high"


class EscalationOutboxStatus(StrEnum):
    """Durable escalation publication lifecycle states."""

    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


__all__ = [
    "EscalationHandoffKind",
    "EscalationOutboxStatus",
    "EscalationPriority",
    "EscalationStatus",
]
