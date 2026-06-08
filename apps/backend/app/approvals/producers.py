"""Producer helpers for creating SME-reviewed approval cases."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, cast

from app.approvals.enums import CaseApprovalEntryCategory, CaseApprovalStatus
from app.approvals.ingress import (
    ApprovalQueueIngressService,
    CaseApprovalReviewRequest,
)
from app.approvals.persistence import CaseApprovalRecord
from app.coordination.contracts.results import CoordinationDispatchResult


class CaseApprovalReviewer(Protocol):
    """Surface needed to run SME review after ingress creation."""

    async def review_case(
        self,
        *,
        approval_case_id: str,
        tenant_id: str,
    ) -> CaseApprovalRecord: ...


async def request_coordination_human_review_case(
    *,
    ingress: ApprovalQueueIngressService | None,
    reviewer: CaseApprovalReviewer | None,
    coordination_result: CoordinationDispatchResult,
    tenant_id: str,
    session_id: str | None = None,
    execution_id: str | None = None,
    ticket_ref: str | None = None,
    issue_summary: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> CaseApprovalRecord | None:
    """Create an approval case for coordination human-review outcomes."""

    if ingress is None or not _coordination_needs_human_review(
        coordination_result
    ):
        return None
    record = await ingress.request_case_review(
        CaseApprovalReviewRequest(
            tenant_id=tenant_id,
            session_id=session_id,
            execution_id=execution_id,
            dispatch_id=str(coordination_result.coordination_id),
            entry_category=CaseApprovalEntryCategory.COORDINATION_HUMAN_REVIEW,
            ticket_ref=ticket_ref,
            issue_summary=(
                issue_summary
                or coordination_result.error
                or coordination_result.outcome.value
            ),
            metadata={
                **dict(metadata or {}),
                "source": "coordination_runtime",
                "coordination_outcome": coordination_result.outcome.value,
                "coordination_error": coordination_result.error,
                "coordination_status": coordination_result.trace.status.value,
                "coordination_message_type": (
                    coordination_result.trace.message_type.value
                ),
                "coordination_sender_id": coordination_result.trace.sender_id,
                "coordination_recipient_id": (
                    coordination_result.trace.recipient_id
                ),
                "coordination_policy_escalated": (
                    coordination_result.is_policy_escalated
                ),
                "coordination_topology_escalated": (
                    coordination_result.is_topology_escalated
                ),
                "coordination_trace_metadata": _json_safe_mapping(
                    coordination_result.trace.metadata
                ),
            },
        ),
        expected_tenant_id=tenant_id,
    )
    if (
        reviewer is not None
        and record.status is CaseApprovalStatus.PENDING_SME_REVIEW
    ):
        return await reviewer.review_case(
            approval_case_id=record.approval_case_id,
            tenant_id=tenant_id,
        )
    return record


async def request_crisis_action_approval_case(
    *,
    ingress: ApprovalQueueIngressService | None,
    reviewer: CaseApprovalReviewer | None,
    tenant_id: str,
    session_id: str,
    execution_id: str,
    dispatch_id: str | None,
    action_approval_id: str,
    tool_name: str,
    payload: Mapping[str, Any],
    governance_decision_id: str | None,
    crisis_policy: str | None,
    issue_summary: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> CaseApprovalRecord | None:
    """Create an approval case for a crisis-governed action approval."""

    if ingress is None:
        return None
    record = await ingress.request_case_review(
        CaseApprovalReviewRequest(
            tenant_id=tenant_id,
            session_id=session_id,
            execution_id=execution_id,
            dispatch_id=dispatch_id,
            entry_category=CaseApprovalEntryCategory.CRISIS_ACTION,
            ticket_ref=f"action-approval:{action_approval_id}",
            issue_summary=issue_summary or crisis_policy or "crisis_action",
            recommended_action={
                "action_approval_id": action_approval_id,
                "requires_execution": True,
                "tool_name": tool_name,
                "payload": dict(payload),
                "governance_decision_id": governance_decision_id,
                "crisis_policy": crisis_policy,
            },
            metadata={
                **dict(metadata or {}),
                "source": "action_orchestration",
                "action_approval_id": action_approval_id,
                "tool_name": tool_name,
                "governance_decision_id": governance_decision_id,
                "crisis_policy": crisis_policy,
            },
        ),
        expected_tenant_id=tenant_id,
    )
    if (
        reviewer is not None
        and record.status is CaseApprovalStatus.PENDING_SME_REVIEW
    ):
        return await reviewer.review_case(
            approval_case_id=record.approval_case_id,
            tenant_id=tenant_id,
        )
    return record


def _coordination_needs_human_review(
    result: CoordinationDispatchResult,
) -> bool:
    # Only policy escalations carry the human-review family of decisions
    # (human_review / tenant_owner_approval / operational_review) where a
    # human signs off so the work proceeds -> the approval queue. Topology
    # escalations are structural routing escalations that belong to the
    # escalation queue, not the approval queue (keep approval != escalation).
    return result.is_policy_escalated


def _json_safe_mapping(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_safe_value(value) for key, value in metadata.items()}


def _json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return _json_safe_mapping(cast(Mapping[str, Any], value))
    if isinstance(value, list):
        return [_json_safe_value(item) for item in cast(list[Any], value)]
    if isinstance(value, tuple):
        return [_json_safe_value(item) for item in cast(tuple[Any, ...], value)]
    return str(value)


__all__ = [
    "CaseApprovalReviewer",
    "request_coordination_human_review_case",
    "request_crisis_action_approval_case",
]
