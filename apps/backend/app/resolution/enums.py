"""Resolution proposal lifecycle enums."""

from __future__ import annotations

from enum import StrEnum


class ResolutionAutonomyDecision(StrEnum):
    """Autonomy disposition for a proposed customer response."""

    AUTO_APPROVED = "auto_approved"
    NEEDS_CUSTOMER_INFO = "needs_customer_info"
    NEEDS_HUMAN_APPROVAL = "needs_human_approval"
    DENIED = "denied"


class ResolutionProposalStatus(StrEnum):
    """Durable state of a resolution proposal."""

    PROPOSED = "proposed"
    AUTO_APPROVED = "auto_approved"
    SEND_ELIGIBLE = "send_eligible"
    PENDING_HUMAN_APPROVAL = "pending_human_approval"
    DENIED = "denied"
    FAILED = "failed"


class ResolutionSupervisorVerdict(StrEnum):
    """Deterministic supervisor gate result."""

    PASS = "pass"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    FAIL = "fail"


class ResolutionGovernanceVerdict(StrEnum):
    """Governance disposition mirrored from the governance vocabulary."""

    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    ESCALATE = "escalate"
    DENY = "deny"
    DEGRADE = "degrade"
    REDACT = "redact"


__all__ = [
    "ResolutionAutonomyDecision",
    "ResolutionGovernanceVerdict",
    "ResolutionProposalStatus",
    "ResolutionSupervisorVerdict",
]
