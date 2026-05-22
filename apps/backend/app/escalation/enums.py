"""Escalation substrate enums."""

from __future__ import annotations

from enum import StrEnum


class EscalationStatus(StrEnum):
    """Human approval queue lifecycle states."""

    PENDING = "pending"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"


__all__ = ["EscalationStatus"]
