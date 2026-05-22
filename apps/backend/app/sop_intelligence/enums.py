"""SOP intelligence proposal vocabulary."""

from __future__ import annotations

from enum import StrEnum


class ApprovalStatus(StrEnum):
    """Lifecycle for SOP intelligence approval proposals."""

    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"


__all__ = ["ApprovalStatus"]
