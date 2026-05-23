"""Escalation substrate enums."""

from __future__ import annotations

from enum import StrEnum


class EscalationStatus(StrEnum):
    """Human approval queue lifecycle states."""

    PENDING = "pending"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"


class EscalationOutboxStatus(StrEnum):
    """Durable escalation publication lifecycle states."""

    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


__all__ = ["EscalationOutboxStatus", "EscalationStatus"]
