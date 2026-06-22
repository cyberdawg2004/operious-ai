"""Break-controls: approve/reject wiring for grounded warranty/refund cases.

A manager reviewing a determinable (eligible/ineligible) REFUND_WARRANTY
case can APPROVE (fires the bound action exactly once, via the existing
CaseApprovalService.approve_case -> ActionApprovalService.approve_in_
transaction -> connector path) or REJECT (denies the bound action,
fires nothing). Both are peer dispositions: a human may approve an
ineligible recommendation (override the denial) or reject an eligible
one (override the recommendation) — recommendation-only means the human
decides either way, not that only the system's preferred outcome is
actionable.

Mirrors test_case_approval_workflow.py's established pattern for this
exact surface (_RecordingActionApprove + a fake executor injected into
CaseApprovalService, not a real connector/network — that rigor belongs
to test_warranty_replacement_connector.py and test_connector_framework.py,
already proven elsewhere) — this file is the REFUND_WARRANTY-specific
proof that approve fires, reject does not, and both are tenant-scoped,
capability-gated, and not re-actionable after resolution.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx
import pytest
from fastapi import FastAPI, Request, Response

from app.api.v1.routers.case_approvals import router as case_approvals_router
from app.approvals.enums import CaseApprovalEntryCategory, CaseApprovalStatus
from app.approvals.exceptions import (
    CaseApprovalLifecycleError,
    CaseApprovalNotFoundError,
    CaseApprovalRuntimeError,
)
from app.approvals.ingress import ApprovalQueueIngressService, CaseApprovalReviewRequest
from app.approvals.persistence import InMemoryCaseApprovalPersistence
from app.dependencies.authority import TENANT_ACTIONS_APPROVE_CAPABILITY
from app.dependencies.services import get_case_approval_service
from app.governance.persistence import InMemoryGovernanceRepository
from app.identity import AuthorityContext
from app.resolution.persistence import InMemoryResolutionProposalPersistence
from app.services.case_approval_service import CaseApprovalService
from app.sme import SmeReviewRuntime

_TENANT = "tenant-warranty-refund-approve-reject"
_SESSION_ID = "11111111-1111-4111-8111-111111111111"
_EXECUTION_ID = "22222222-2222-4222-8222-222222222222"
_DISPATCH_ID = "33333333-3333-4333-8333-333333333333"
_ACTION_APPROVAL_ID = "action-approval-warranty-1"


class _RecordingActionApprove:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None, str, str]] = []

    async def __call__(
        self,
        approval_id: str,
        approved_by: str,
        note: str | None,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> object:
        self.calls.append((approval_id, approved_by, note, tenant_id, expected_tenant_id))
        return {"status": "executed"}


class _RecordingActionDeny:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str, str]] = []

    async def __call__(
        self,
        approval_id: str,
        denied_by: str,
        reason: str,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> object:
        self.calls.append((approval_id, denied_by, reason, tenant_id, expected_tenant_id))
        return {"status": "denied"}


def _warranty_refund_request(
    *,
    verdict: str,
    action_approval_id: str | None = _ACTION_APPROVAL_ID,
    recommended_remedy: str | None = "replacement",
) -> CaseApprovalReviewRequest:
    action: dict[str, object] = {
        "type": "warranty_claim",
        "requires_execution": True,
        "tool_name": "replacement.order",
        "product_sku": "sku-1",
        "warranty_refund_eligibility": {
            "claim_type": "defective",
            "verdict": verdict,
            "recommended_remedy": recommended_remedy,
            "recommended_remedy_availability": "available",
            "missing_evidence": [],
            "grounding": [],
        },
    }
    if action_approval_id is not None:
        action["action_approval_id"] = action_approval_id
    return CaseApprovalReviewRequest(
        tenant_id=_TENANT,
        session_id=_SESSION_ID,
        execution_id=_EXECUTION_ID,
        dispatch_id=_DISPATCH_ID,
        entry_category=CaseApprovalEntryCategory.REFUND_WARRANTY,
        issue_summary=f"defective: {verdict}",
        product="sku-1",
        recommended_action=action,
    )


async def _reviewed_case(
    *,
    service: CaseApprovalService,
    persistence: InMemoryCaseApprovalPersistence,
    request: CaseApprovalReviewRequest,
):
    ingress = ApprovalQueueIngressService(persistence=persistence)
    record = await ingress.request_case_review(request, expected_tenant_id=_TENANT)
    return await service.review_case(
        approval_case_id=record.approval_case_id, tenant_id=_TENANT
    )


def _service(
    *,
    persistence: InMemoryCaseApprovalPersistence,
    approve: _RecordingActionApprove | None = None,
    deny: _RecordingActionDeny | None = None,
) -> CaseApprovalService:
    return CaseApprovalService(
        persistence=persistence,
        sme_runtime=SmeReviewRuntime(),
        resolution_repository=InMemoryResolutionProposalPersistence(),
        governance_repository=InMemoryGovernanceRepository(),
        action_approval_approve=approve,
        action_approval_deny=deny,
    )


# ─── approve fires exactly once, bound to recommendation + approver ───────


@pytest.mark.asyncio
async def test_eligible_case_approve_fires_bound_action_exactly_once() -> None:
    persistence = InMemoryCaseApprovalPersistence()
    approve = _RecordingActionApprove()
    deny = _RecordingActionDeny()
    service = _service(persistence=persistence, approve=approve, deny=deny)
    reviewed = await _reviewed_case(
        service=service,
        persistence=persistence,
        request=_warranty_refund_request(verdict="eligible"),
    )

    approved = await service.approve_case(
        approval_case_id=reviewed.approval_case_id,
        tenant_id=_TENANT,
        approved_by="manager-1",
        note="confirmed within warranty window",
    )

    assert approved.status is CaseApprovalStatus.APPROVED
    assert approved.resolved_by == "manager-1"
    assert approve.calls == [
        (_ACTION_APPROVAL_ID, "manager-1", "confirmed within warranty window", _TENANT, _TENANT)
    ]
    assert deny.calls == []


@pytest.mark.asyncio
async def test_human_can_override_ineligible_verdict_by_approving() -> None:
    """Recommendation-only: the system recommended denial, but the human
    is the actual decision-maker and may approve anyway — and that
    override fires the SAME bound action."""
    persistence = InMemoryCaseApprovalPersistence()
    approve = _RecordingActionApprove()
    service = _service(persistence=persistence, approve=approve)
    reviewed = await _reviewed_case(
        service=service,
        persistence=persistence,
        request=_warranty_refund_request(verdict="ineligible"),
    )

    approved = await service.approve_case(
        approval_case_id=reviewed.approval_case_id,
        tenant_id=_TENANT,
        approved_by="manager-override",
        note="goodwill exception",
    )

    assert approved.status is CaseApprovalStatus.APPROVED
    assert approve.calls == [
        (_ACTION_APPROVAL_ID, "manager-override", "goodwill exception", _TENANT, _TENANT)
    ]


# ─── reject fires nothing ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reject_denies_bound_action_and_never_calls_approve_executor() -> None:
    persistence = InMemoryCaseApprovalPersistence()
    approve = _RecordingActionApprove()
    deny = _RecordingActionDeny()
    service = _service(persistence=persistence, approve=approve, deny=deny)
    reviewed = await _reviewed_case(
        service=service,
        persistence=persistence,
        request=_warranty_refund_request(verdict="eligible"),
    )

    rejected = await service.reject_case(
        approval_case_id=reviewed.approval_case_id,
        tenant_id=_TENANT,
        rejected_by="manager-2",
        reason="duplicate claim",
    )

    assert rejected.status is CaseApprovalStatus.REJECTED
    assert rejected.resolved_by == "manager-2"
    assert rejected.resolution_note == "duplicate claim"
    assert approve.calls == []
    assert deny.calls == [
        (_ACTION_APPROVAL_ID, "manager-2", "duplicate claim", _TENANT, _TENANT)
    ]


@pytest.mark.asyncio
async def test_reject_with_no_reason_still_denies_with_a_nonempty_fallback_note() -> None:
    """The CASE-level reason is genuinely optional; the bound action's
    denial still requires a non-empty note structurally (ActionApproval
    Service.deny's own invariant) — a sensible fallback satisfies that
    without forcing the human to type something."""
    persistence = InMemoryCaseApprovalPersistence()
    deny = _RecordingActionDeny()
    service = _service(persistence=persistence, deny=deny)
    reviewed = await _reviewed_case(
        service=service,
        persistence=persistence,
        request=_warranty_refund_request(verdict="ineligible"),
    )

    rejected = await service.reject_case(
        approval_case_id=reviewed.approval_case_id,
        tenant_id=_TENANT,
        rejected_by="manager-3",
        reason=None,
    )

    assert rejected.status is CaseApprovalStatus.REJECTED
    assert rejected.resolution_note is None
    assert len(deny.calls) == 1
    assert deny.calls[0][2]  # non-empty fallback note reached the denier


@pytest.mark.asyncio
async def test_reject_action_bound_case_without_denier_fails_closed() -> None:
    """Symmetric with approve's fail-closed behavior: a case bound to a
    real action must not be marked rejected while that action is left
    dangling pending."""
    persistence = InMemoryCaseApprovalPersistence()
    service = _service(persistence=persistence)  # no deny executor configured
    reviewed = await _reviewed_case(
        service=service,
        persistence=persistence,
        request=_warranty_refund_request(verdict="eligible"),
    )

    with pytest.raises(CaseApprovalRuntimeError):
        await service.reject_case(
            approval_case_id=reviewed.approval_case_id,
            tenant_id=_TENANT,
            rejected_by="manager-4",
            reason=None,
        )

    after = await service.get_case(
        approval_case_id=reviewed.approval_case_id, tenant_id=_TENANT
    )
    assert after is not None
    assert after.status is CaseApprovalStatus.AWAITING_APPROVAL


# ─── no auto-approve / not re-actionable after resolution ─────────────────


@pytest.mark.asyncio
async def test_case_is_not_approvable_before_review() -> None:
    """Creating the case alone never executes anything — only an explicit
    human approve action does."""
    persistence = InMemoryCaseApprovalPersistence()
    approve = _RecordingActionApprove()
    ingress = ApprovalQueueIngressService(persistence=persistence)
    record = await ingress.request_case_review(
        _warranty_refund_request(verdict="eligible"), expected_tenant_id=_TENANT
    )
    service = _service(persistence=persistence, approve=approve)

    with pytest.raises(CaseApprovalLifecycleError):
        await service.approve_case(
            approval_case_id=record.approval_case_id,
            tenant_id=_TENANT,
            approved_by="manager-5",
            note=None,
        )
    assert approve.calls == []


@pytest.mark.asyncio
async def test_double_approve_is_rejected_not_re_executed() -> None:
    persistence = InMemoryCaseApprovalPersistence()
    approve = _RecordingActionApprove()
    service = _service(persistence=persistence, approve=approve)
    reviewed = await _reviewed_case(
        service=service,
        persistence=persistence,
        request=_warranty_refund_request(verdict="eligible"),
    )
    await service.approve_case(
        approval_case_id=reviewed.approval_case_id,
        tenant_id=_TENANT,
        approved_by="manager-6",
        note=None,
    )
    assert len(approve.calls) == 1

    with pytest.raises(CaseApprovalLifecycleError):
        await service.approve_case(
            approval_case_id=reviewed.approval_case_id,
            tenant_id=_TENANT,
            approved_by="manager-7",
            note=None,
        )
    assert len(approve.calls) == 1  # not fired a second time


@pytest.mark.asyncio
async def test_double_reject_is_rejected_not_re_recorded() -> None:
    persistence = InMemoryCaseApprovalPersistence()
    deny = _RecordingActionDeny()
    service = _service(persistence=persistence, deny=deny)
    reviewed = await _reviewed_case(
        service=service,
        persistence=persistence,
        request=_warranty_refund_request(verdict="eligible"),
    )
    await service.reject_case(
        approval_case_id=reviewed.approval_case_id,
        tenant_id=_TENANT,
        rejected_by="manager-8",
        reason="no evidence",
    )
    assert len(deny.calls) == 1

    with pytest.raises(CaseApprovalLifecycleError):
        await service.reject_case(
            approval_case_id=reviewed.approval_case_id,
            tenant_id=_TENANT,
            rejected_by="manager-9",
            reason="trying again",
        )
    assert len(deny.calls) == 1


@pytest.mark.asyncio
async def test_rejected_case_cannot_then_be_approved() -> None:
    persistence = InMemoryCaseApprovalPersistence()
    approve = _RecordingActionApprove()
    deny = _RecordingActionDeny()
    service = _service(persistence=persistence, approve=approve, deny=deny)
    reviewed = await _reviewed_case(
        service=service,
        persistence=persistence,
        request=_warranty_refund_request(verdict="eligible"),
    )
    await service.reject_case(
        approval_case_id=reviewed.approval_case_id,
        tenant_id=_TENANT,
        rejected_by="manager-10",
        reason="denied",
    )

    with pytest.raises(CaseApprovalLifecycleError):
        await service.approve_case(
            approval_case_id=reviewed.approval_case_id,
            tenant_id=_TENANT,
            approved_by="manager-11",
            note=None,
        )
    assert approve.calls == []


# ─── tenant-scoped ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reject_is_tenant_scoped_cross_tenant_not_found() -> None:
    persistence = InMemoryCaseApprovalPersistence()
    service = _service(persistence=persistence, deny=_RecordingActionDeny())
    reviewed = await _reviewed_case(
        service=service,
        persistence=persistence,
        request=_warranty_refund_request(verdict="eligible"),
    )

    with pytest.raises(CaseApprovalNotFoundError):
        await service.reject_case(
            approval_case_id=reviewed.approval_case_id,
            tenant_id="tenant-other",
            rejected_by="intruder",
            reason="should not work",
        )


@pytest.mark.asyncio
async def test_approve_is_tenant_scoped_cross_tenant_not_found() -> None:
    persistence = InMemoryCaseApprovalPersistence()
    service = _service(persistence=persistence, approve=_RecordingActionApprove())
    reviewed = await _reviewed_case(
        service=service,
        persistence=persistence,
        request=_warranty_refund_request(verdict="eligible"),
    )

    with pytest.raises(CaseApprovalNotFoundError):
        await service.approve_case(
            approval_case_id=reviewed.approval_case_id,
            tenant_id="tenant-other",
            approved_by="intruder",
            note=None,
        )


# ─── dual-layer capability gate: the BACKEND router is the real boundary ──


class _UnexpectedRejectService:
    """If the router's gate ever passed a no-capability request through,
    this would prove it by actually running — and the test would fail on
    that, not on a 403 it never reached."""

    async def reject_case(self, **kwargs: object) -> object:
        raise AssertionError("reject service should not run without capability")


def _no_capability_test_app() -> FastAPI:
    app = FastAPI()
    authority = AuthorityContext.from_raw(
        tenant_id=_TENANT,
        principal_id="operator-no-cap",
        capabilities=frozenset({"tenant.approvals.read"}),
    )

    @app.middleware("http")
    async def _bind_authority(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.authority = authority
        return await call_next(request)

    app.dependency_overrides[get_case_approval_service] = (
        lambda: _UnexpectedRejectService()
    )
    app.include_router(case_approvals_router, prefix="/approvals/cases")
    return app


@pytest.mark.asyncio
async def test_reject_endpoint_denies_without_actions_approve_capability() -> None:
    """The UI hides the reject button without this capability, but the
    backend router is the actual security boundary — proven here by a
    request that never had a UI to hide anything from."""
    transport = httpx.ASGITransport(app=_no_capability_test_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/approvals/cases/case-1/reject", json={"reason": "should not work"}
        )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "code": "capability_required",
        "capability": TENANT_ACTIONS_APPROVE_CAPABILITY,
    }
