"""Approval-record value object.

The `ApprovalRecord` is the cryptographically auditable proof
that a human (or delegated reviewer) made an explicit decision.
Every status transition out of CANDIDATE / PROPOSED requires one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.organizational_intelligence.enums import (
    ApprovalAuthorityKind,
    ApprovalDecision,
)
from app.organizational_intelligence.identity import ApprovalId


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    """One immutable approval / rejection / deferral record.

    Attributes:
        approval_id:        Stable identifier (UUID5-derivable).
        target_id:          Identifier of the artifact / proposal /
                             recommendation this decision applies
                             to. Stored as opaque uuid.UUID.
        target_kind:        Free-form classification string
                             (e.g. ``"memory_artifact"``,
                             ``"sop"``, ``"recommendation"``,
                             ``"candidate_pattern"``).
        decision:           APPROVED / REJECTED / DEFERRED.
        authority:          Who decided.
        approver_handle:    Free-form attribution string;
                             **required** for HUMAN_OPERATOR /
                             HUMAN_REVIEWER authority.
        decided_at:         UTC timestamp of the decision.
        rationale:          Free-form human rationale.
        attributes:         Canonical metadata payload.
    """

    approval_id: ApprovalId
    target_id: uuid.UUID
    target_kind: str
    decision: ApprovalDecision
    authority: ApprovalAuthorityKind
    approver_handle: str
    decided_at: datetime
    rationale: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict[str, Any])

    def __post_init__(self) -> None:
        if not self.target_kind:
            raise ValueError(
                "ApprovalRecord.target_kind must be non-empty"
            )
        if self.decided_at.tzinfo is None:
            raise ValueError(
                "ApprovalRecord.decided_at must be tz-aware"
            )
        if (
            self.authority
            in (
                ApprovalAuthorityKind.HUMAN_OPERATOR,
                ApprovalAuthorityKind.HUMAN_REVIEWER,
            )
            and not self.approver_handle
        ):
            raise ValueError(
                "ApprovalRecord.approver_handle is required for "
                "human authorities"
            )


__all__ = ["ApprovalRecord"]
