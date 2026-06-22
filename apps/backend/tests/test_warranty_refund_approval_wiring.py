"""W2 break-controls: agent_tasks.py routing of W1 eligibility into the
approval queue.

_request_resolution_approval_cases creates a REFUND_WARRANTY case (with
the grounding trail) for determinable (eligible/ineligible) verdicts, and
never for cannot_determine — which instead reaches a human through the
existing RESOLUTION_REQUIRE_APPROVAL/RESOLUTION_NEEDS_HUMAN_APPROVAL
categories, never silently.

Following the established convention for this exact code path (see
test_case_approval_workflow.py's _request_resolution_approval_cases_with_
retry tests): in-memory persistence + monkeypatch, not real Postgres —
this surface is already proven equivalent to Postgres semantics by that
existing precedent, and W1's own tenant-isolation test used the same
in-memory approach. Private-symbol access on the agent_tasks module uses
cast(Any, ...)/getattr, mirroring that same file's established idiom for
keeping this file pyright-clean rather than excluding it outright.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Any, cast

import pytest

from app.agents.tools.approvals import InMemoryActionApprovalRepository
from app.approvals.enums import CaseApprovalEntryCategory, CaseApprovalStatus
from app.approvals.persistence import (
    CaseApprovalQuery,
    CaseApprovalRecord,
    InMemoryCaseApprovalPersistence,
)
from app.resolution.enums import (
    ResolutionAutonomyDecision,
    ResolutionGovernanceVerdict,
    ResolutionProposalStatus,
    ResolutionSupervisorVerdict,
)
from app.resolution.identity import as_resolution_proposal_id
from app.resolution.persistence import ResolutionProposalRecord
from app.workers import agent_tasks

_TENANT = "tenant-warranty-refund-wiring"
_SESSION_ID = "11111111-1111-4111-8111-111111111111"
_EXECUTION_ID = "22222222-2222-4222-8222-222222222222"
_DISPATCH_ID = "33333333-3333-4333-8333-333333333333"

_worker = cast(Any, agent_tasks)


class _FakeNestedTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc_info: object) -> bool:
        del exc_info
        return False


class _FakeSession:
    def begin_nested(self) -> _FakeNestedTransaction:
        return _FakeNestedTransaction()


def _proposal_with_eligibility(
    *,
    eligibility: dict[str, Any],
    governance_verdict: ResolutionGovernanceVerdict = (
        ResolutionGovernanceVerdict.ALLOW
    ),
    autonomy_decision: ResolutionAutonomyDecision = (
        ResolutionAutonomyDecision.AUTO_APPROVED
    ),
    confidence: float = 0.9,
    tenant_id: str = _TENANT,
) -> ResolutionProposalRecord:
    now = datetime.now(timezone.utc)
    return ResolutionProposalRecord(
        proposal_id=as_resolution_proposal_id(
            "44444444-4444-4444-8444-444444444444"
        ),
        tenant_id=tenant_id,
        session_id=_SESSION_ID,
        execution_id=_EXECUTION_ID,
        dispatch_id=_DISPATCH_ID,
        diagnostic_event_id=None,
        proposed_customer_reply="We're reviewing your warranty claim.",
        resolution_category="warranty_claim_category",
        confidence=confidence,
        recommended_actions=(
            {
                "type": "warranty_claim",
                "requires_execution": True,
                "tool_name": "warranty.claim",
                "product_sku": "sku-1",
                "warranty_refund_eligibility": eligibility,
            },
        ),
        evidence=(),
        supervisor_verdict=ResolutionSupervisorVerdict.NEEDS_HUMAN_REVIEW,
        governance_verdict=governance_verdict,
        autonomy_decision=autonomy_decision,
        status=ResolutionProposalStatus.PENDING_HUMAN_APPROVAL,
        created_at=now,
        updated_at=now,
    )


def _eligible_eligibility() -> dict[str, Any]:
    return {
        "claim_type": "warranty_claim",
        "verdict": "eligible",
        "recommended_remedy": "replacement",
        "missing_evidence": [],
        "grounding": [
            {
                "name": "within_warranty_window",
                "passed": True,
                "rule": "warranty_window_days=730",
                "evidence_field": "purchase_date",
                "evidence_value": "2026-01-01",
                "evidence_confidence": "high",
            },
        ],
    }


def _ineligible_eligibility() -> dict[str, Any]:
    return {
        "claim_type": "warranty_claim",
        "verdict": "ineligible",
        "recommended_remedy": None,
        "missing_evidence": [],
        "grounding": [
            {
                "name": "authorized_reseller",
                "passed": False,
                "rule": "authorized_resellers=['amazon.com']",
                "evidence_field": "seller",
                "evidence_value": "shady-reseller.example",
                "evidence_confidence": "high",
            },
        ],
    }


def _cannot_determine_eligibility() -> dict[str, Any]:
    return {
        "claim_type": "warranty_claim",
        "verdict": "cannot_determine",
        "recommended_remedy": None,
        "missing_evidence": ["purchase_date"],
        "grounding": [],
    }


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    persistence: InMemoryCaseApprovalPersistence,
    *,
    action_approvals: InMemoryActionApprovalRepository | None = None,
) -> None:
    def _approval_persistence_factory(
        session: object, data_protection: object | None = None
    ) -> InMemoryCaseApprovalPersistence:
        del session, data_protection
        return persistence

    def _resolution_persistence_factory(
        session: object, data_protection: object | None = None
    ) -> object:
        del session, data_protection
        return object()

    action_approval_repository = action_approvals or InMemoryActionApprovalRepository()

    def _action_approval_repository_factory(
        session: object,
    ) -> InMemoryActionApprovalRepository:
        del session
        return action_approval_repository

    class _NoOpReviewService:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def review_case(
            self, *, approval_case_id: str, tenant_id: str
        ) -> CaseApprovalRecord:
            record = await persistence.get_case(
                approval_case_id, expected_tenant_id=tenant_id
            )
            assert record is not None
            return record

    monkeypatch.setattr(
        agent_tasks, "PostgresCaseApprovalPersistence", _approval_persistence_factory
    )
    monkeypatch.setattr(
        agent_tasks,
        "PostgresResolutionProposalPersistence",
        _resolution_persistence_factory,
    )
    monkeypatch.setattr(agent_tasks, "CaseApprovalService", _NoOpReviewService)
    monkeypatch.setattr(agent_tasks, "build_sme_review_runtime", lambda: object())
    monkeypatch.setattr(
        agent_tasks,
        "PostgresActionApprovalRepository",
        _action_approval_repository_factory,
    )


def _work_item(*, tenant_id: str = _TENANT) -> Any:
    work_item = getattr(agent_tasks, "_DiagnosticExecutionWorkItem")
    return work_item(
        execution_id=_EXECUTION_ID,
        attempt_id="attempt-1",
        attempt_number=1,
        dispatch_id=_DISPATCH_ID,
        session_id=_SESSION_ID,
        tenant_id=tenant_id,
        content="Customer asks about a warranty replacement.",
    )


async def _run_and_fetch_cases(
    monkeypatch: pytest.MonkeyPatch,
    proposal: ResolutionProposalRecord,
    *,
    tenant_id: str = _TENANT,
) -> tuple[CaseApprovalRecord, ...]:
    persistence = InMemoryCaseApprovalPersistence()
    _install_fakes(monkeypatch, persistence)
    await _worker._request_resolution_approval_cases_with_retry(
        session=cast(Any, _FakeSession()),
        proposal=proposal,
        work_item=_work_item(tenant_id=tenant_id),
        data_protection=None,
        governance_repository=cast(Any, object()),
    )
    page = await persistence.list_cases(
        CaseApprovalQuery(limit=10), expected_tenant_id=tenant_id
    )
    return page.items


@pytest.mark.asyncio
async def test_eligible_verdict_creates_refund_warranty_case_with_grounding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proposal = _proposal_with_eligibility(eligibility=_eligible_eligibility())
    records = await _run_and_fetch_cases(monkeypatch, proposal)

    assert len(records) == 1
    record = records[0]
    assert record.entry_category is CaseApprovalEntryCategory.REFUND_WARRANTY
    assert record.product == "sku-1"
    assert record.issue_summary == "warranty_claim: eligible"
    assert record.recommended_action is not None
    eligibility = record.recommended_action["warranty_refund_eligibility"]
    assert eligibility[
        "grounding"
    ], "grounding must reach the case, not just the verdict"
    assert record.metadata["warranty_refund_eligibility"] == [
        _eligible_eligibility()
    ]


@pytest.mark.asyncio
async def test_ineligible_verdict_creates_refund_warranty_case_for_human_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A denial is never auto-rejected silently — a human reviews it too."""
    proposal = _proposal_with_eligibility(eligibility=_ineligible_eligibility())
    records = await _run_and_fetch_cases(monkeypatch, proposal)

    assert len(records) == 1
    record = records[0]
    assert record.entry_category is CaseApprovalEntryCategory.REFUND_WARRANTY
    assert record.issue_summary == "warranty_claim: ineligible"
    assert record.recommended_action is not None
    grounding = record.recommended_action["warranty_refund_eligibility"]["grounding"]
    assert grounding[0]["passed"] is False


@pytest.mark.asyncio
async def test_cannot_determine_does_not_create_refund_warranty_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No silent drop: cannot_determine reaches a human via the existing
    RESOLUTION_REQUIRE_APPROVAL/NEEDS_HUMAN_APPROVAL categories, never via
    a REFUND_WARRANTY case (there's no determinable verdict to review)."""
    proposal = _proposal_with_eligibility(
        eligibility=_cannot_determine_eligibility(),
        governance_verdict=ResolutionGovernanceVerdict.REQUIRE_APPROVAL,
        autonomy_decision=ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL,
    )
    records = await _run_and_fetch_cases(monkeypatch, proposal)

    assert len(records) == 1
    record = records[0]
    assert record.entry_category is not CaseApprovalEntryCategory.REFUND_WARRANTY
    assert record.entry_category is (
        CaseApprovalEntryCategory.RESOLUTION_REQUIRE_APPROVAL
    )
    # The cannot_determine detail still reaches the human via metadata.
    assert record.metadata["warranty_refund_eligibility"] == [
        _cannot_determine_eligibility()
    ]


@pytest.mark.asyncio
async def test_no_execution_path_is_invoked_when_case_is_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Creating the case (and, since the approve/reject wiring, binding a
    PENDING action-approval to it) is still the end of this function's
    responsibility — it must never reach an actual connector-invocation
    symbol. A pending action-approval is not an execution: nothing fires
    until a human approves it through CaseApprovalService.approve_case,
    a completely separate code path this function never calls."""
    source = inspect.getsource(_worker._request_resolution_approval_cases)
    forbidden = ("ToolInvoker", ".invoke(", "re_invoke_approved_action", "execute_action")
    assert not any(token in source for token in forbidden)

    proposal = _proposal_with_eligibility(eligibility=_eligible_eligibility())
    action_approvals = InMemoryActionApprovalRepository()
    persistence = InMemoryCaseApprovalPersistence()
    monkeypatch_target = monkeypatch
    _install_fakes(monkeypatch_target, persistence, action_approvals=action_approvals)
    await _worker._request_resolution_approval_cases_with_retry(
        session=cast(Any, _FakeSession()),
        proposal=proposal,
        work_item=_work_item(),
        data_protection=None,
        governance_repository=cast(Any, object()),
    )
    page = await persistence.list_cases(
        CaseApprovalQuery(limit=10), expected_tenant_id=_TENANT
    )
    records = page.items
    assert records[0].status is CaseApprovalStatus.PENDING_SME_REVIEW

    action = records[0].recommended_action
    assert action is not None
    approval_id = action.get("action_approval_id")
    assert approval_id is not None
    bound = await action_approvals.get_approval(
        str(approval_id), expected_tenant_id=_TENANT
    )
    assert bound is not None
    assert bound.status == "pending"


@pytest.mark.asyncio
async def test_refund_warranty_case_is_tenant_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_a = "tenant-warranty-refund-wiring-a"
    proposal = _proposal_with_eligibility(
        eligibility=_eligible_eligibility(), tenant_id=tenant_a
    )
    persistence = InMemoryCaseApprovalPersistence()
    _install_fakes(monkeypatch, persistence)
    await _worker._request_resolution_approval_cases_with_retry(
        session=cast(Any, _FakeSession()),
        proposal=proposal,
        work_item=_work_item(tenant_id=tenant_a),
        data_protection=None,
        governance_repository=cast(Any, object()),
    )

    own_tenant_page = await persistence.list_cases(
        CaseApprovalQuery(limit=10), expected_tenant_id=tenant_a
    )
    other_tenant_page = await persistence.list_cases(
        CaseApprovalQuery(limit=10),
        expected_tenant_id="tenant-warranty-refund-wiring-b",
    )
    assert len(own_tenant_page.items) == 1
    assert len(other_tenant_page.items) == 0
