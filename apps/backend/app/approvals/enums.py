"""Case approval queue lifecycle vocabulary."""

from __future__ import annotations

from enum import StrEnum


class CaseApprovalEntryCategory(StrEnum):
    """Sources that can request SME review + human sign-off."""

    RESOLUTION_REQUIRE_APPROVAL = "resolution_require_approval"
    RESOLUTION_NEEDS_HUMAN_APPROVAL = "resolution_needs_human_approval"
    REFUND_WARRANTY = "refund_warranty"
    LOW_CONFIDENCE = "low_confidence"
    COORDINATION_HUMAN_REVIEW = "coordination_human_review"
    CRISIS_ACTION = "crisis_action"


class CaseApprovalStatus(StrEnum):
    """Durable lifecycle for one case approval record."""

    PENDING_SME_REVIEW = "pending_sme_review"
    AWAITING_APPROVAL = "awaiting_approval"
    GUIDANCE_IN_PROGRESS = "guidance_in_progress"
    APPROVED = "approved"
    ESCALATED = "escalated"
    FAILED = "failed"


class CaseApprovalOutboxStatus(StrEnum):
    """Durable publication state for approval queue notifications."""

    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


TERMINAL_CASE_APPROVAL_STATUSES: frozenset[CaseApprovalStatus] = frozenset(
    {
        CaseApprovalStatus.APPROVED,
        CaseApprovalStatus.ESCALATED,
        CaseApprovalStatus.FAILED,
    }
)


__all__ = [
    "CaseApprovalEntryCategory",
    "CaseApprovalOutboxStatus",
    "CaseApprovalStatus",
    "TERMINAL_CASE_APPROVAL_STATUSES",
]
