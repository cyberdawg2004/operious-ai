"""Approval-gate functions.

Every promotion / supersession / registration / review path
threads through one of the helpers below. They are PURE
validators — they raise on violation, return ``None`` on success,
and never mutate input.
"""

from __future__ import annotations

import uuid

from app.organizational_intelligence.enums import (
    ApprovalAuthorityKind,
    ApprovalDecision,
)
from app.organizational_intelligence.exceptions import (
    IntelligenceApprovalError,
    IntelligenceAuthorityError,
)
from app.organizational_intelligence.models.approval import (
    ApprovalRecord,
)


def _ensure_human_authority(approval: ApprovalRecord) -> None:
    if approval.authority not in (
        ApprovalAuthorityKind.HUMAN_OPERATOR,
        ApprovalAuthorityKind.HUMAN_REVIEWER,
    ):
        raise IntelligenceAuthorityError(
            "approval authority must be HUMAN_OPERATOR or "
            "HUMAN_REVIEWER; substrate is forbidden from "
            "approving its own evolution"
        )


def _ensure_target_match(
    *,
    approval: ApprovalRecord,
    target_id: uuid.UUID,
    target_kind: str,
) -> None:
    if approval.target_id != target_id:
        raise IntelligenceAuthorityError(
            f"approval target_id {approval.target_id!r} does not "
            f"match expected {target_id!r}"
        )
    if approval.target_kind != target_kind:
        raise IntelligenceAuthorityError(
            f"approval target_kind {approval.target_kind!r} does "
            f"not match expected {target_kind!r}"
        )


def require_approval_for_promotion(
    *,
    approval: ApprovalRecord,
    target_id: uuid.UUID,
    target_kind: str,
) -> None:
    """Approve-as-promotion gate.

    The decision MUST be ``APPROVED`` and the authority MUST be
    a human authority.
    """
    _ensure_human_authority(approval)
    _ensure_target_match(
        approval=approval,
        target_id=target_id,
        target_kind=target_kind,
    )
    if approval.decision is not ApprovalDecision.APPROVED:
        raise IntelligenceApprovalError(
            "promotion requires ApprovalDecision.APPROVED; got "
            f"{approval.decision.value}"
        )


def require_approval_for_registration(
    *,
    approval: ApprovalRecord,
    target_kind: str,
) -> None:
    """Registration gate (e.g. communication-pattern registration).

    The decision MUST be ``APPROVED``. The substrate does NOT
    require ``target_id`` matching — registration is for newly-
    minted resources whose id the substrate derives.
    """
    _ensure_human_authority(approval)
    if approval.target_kind != target_kind:
        raise IntelligenceAuthorityError(
            f"approval target_kind {approval.target_kind!r} does "
            f"not match expected {target_kind!r}"
        )
    if approval.decision is not ApprovalDecision.APPROVED:
        raise IntelligenceApprovalError(
            "registration requires ApprovalDecision.APPROVED; "
            f"got {approval.decision.value}"
        )


def require_approval_for_supersession(
    *,
    approval: ApprovalRecord,
    predecessor_id: uuid.UUID,
    successor_id: uuid.UUID,
    target_kind: str,
) -> None:
    """Supersession gate.

    The substrate accepts an approval that targets either the
    predecessor (a "retirement" framing) or the successor (a
    "promotion" framing). Either way, the decision must be
    APPROVED and the authority must be human.
    """
    _ensure_human_authority(approval)
    if approval.decision is not ApprovalDecision.APPROVED:
        raise IntelligenceApprovalError(
            "supersession requires ApprovalDecision.APPROVED"
        )
    if approval.target_id not in (
        predecessor_id,
        successor_id,
    ):
        raise IntelligenceAuthorityError(
            "supersession approval must target either the "
            "predecessor or the successor"
        )
    if approval.target_kind != target_kind:
        raise IntelligenceAuthorityError(
            f"supersession approval target_kind "
            f"{approval.target_kind!r} does not match expected "
            f"{target_kind!r}"
        )


def require_approval_for_review(
    *,
    approval: ApprovalRecord,
    target_id: uuid.UUID,
    target_kind: str,
) -> None:
    """Review gate.

    Recommendations may be APPROVED, REJECTED, or DEFERRED — but
    the decision must come from a human authority.
    """
    _ensure_human_authority(approval)
    _ensure_target_match(
        approval=approval,
        target_id=target_id,
        target_kind=target_kind,
    )


__all__ = [
    "require_approval_for_promotion",
    "require_approval_for_registration",
    "require_approval_for_review",
    "require_approval_for_supersession",
]
