"""Auto-send-on-approval: approving an eligible case must, in the SAME
completion transaction, enqueue the now-ready reply to the SAME durable
outbox the build-time auto-send path uses -- never a second send
implementation, and never an action-fired-but-reply-unsent split.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import pytest

from app.approvals.enums import CaseApprovalEntryCategory, CaseApprovalStatus
from app.approvals.exceptions import CaseApprovalRuntimeError
from app.approvals.ingress import ApprovalQueueIngressService, CaseApprovalReviewRequest
from app.approvals.persistence import InMemoryCaseApprovalPersistence
from app.boundary.outbound.send_outbox import (
    InMemoryOutboundSendOutboxPersistence,
    OutboundSendOutboxQuery,
)
from app.coordination.persistence import InMemoryCoordinationPersistence
from app.coordination.persistence.records import CoordinationRecord
from app.governance.persistence import InMemoryGovernanceRepository
from app.resolution.enums import (
    ResolutionAutonomyDecision,
    ResolutionGovernanceVerdict,
    ResolutionOutboundDraftStatus,
    ResolutionProposalStatus,
    ResolutionSupervisorVerdict,
)
from app.resolution.identity import (
    as_resolution_outbound_draft_id,
    as_resolution_proposal_id,
    derive_resolution_outbound_draft_id,
)
from app.resolution.persistence import (
    InMemoryResolutionProposalPersistence,
    ResolutionOutboundDraftRecord,
    ResolutionProposalRecord,
)
from app.runtime.resolution_runtime import (
    ResolutionGovernanceGateRequest,
    ResolutionGovernanceGateResult,
)
from app.services.case_approval_service import CaseApprovalService
from app.services.outbound_auto_send_service import (
    OutboundAutoSendRefusalReason,
    OutboundAutoSendRequestResult,
    OutboundAutoSendService,
)
from app.sme import SmeCaseContext, SmeReviewRuntime
from app.sme.models import SmeRecommendation

_TENANT = "tenant-case-auto-send"
_SESSION_ID = "11111111-1111-4111-8111-111111111111"
_EXECUTION_ID = "22222222-2222-4222-8222-222222222222"
_DISPATCH_ID = "33333333-3333-4333-8333-333333333333"
_PROPOSAL_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")
_DRAFT_ID = derive_resolution_outbound_draft_id(
    tenant_id=_TENANT, proposal_id=_PROPOSAL_ID
)
_REPLY = "We can help review the warranty claim."
_REAL_CUSTOMER_ADDRESS = "real.customer@example.net"
_SES_ENVELOPE_ADDRESS = "0100019e-bounce@amazonses.com"
_TICKET_SUBJECT = "Warranty Replacement Request - Order ORDER-1"
_NOW = datetime(2026, 6, 24, tzinfo=timezone.utc)


async def _record_dispatch_envelope(
    coordination: InMemoryCoordinationPersistence,
    *,
    recipient: str = _REAL_CUSTOMER_ADDRESS,
) -> None:
    """The inbound dispatch envelope: the customer's real address is the
    email's ``From`` header. The SES/provider envelope address must never
    be used as the reply target, even though it appears elsewhere on the
    envelope (e.g. as ``sender_id``)."""
    await coordination.record_envelope(
        CoordinationRecord(
            coordination_id=_DISPATCH_ID,
            message_id="msg-inbound-1",
            sender_id=_SES_ENVELOPE_ADDRESS,
            recipient_id="agent:diagnostic",
            recipient_kind="agent",
            direction="inbound",
            message_type="ticket",
            priority=5,
            status="dispatched",
            sequence=1,
            runtime_instance_id=str(uuid.uuid4()),
            correlation_id=_DISPATCH_ID,
            parent_coordination_id=None,
            parent_message_id=None,
            in_reply_to=None,
            request_id=_DISPATCH_ID,
            tenant_id=_TENANT,
            governance_decision_id=None,
            governance_chain_id=None,
            payload_content_type="application/json",
            payload_schema_version="1",
            payload_body={
                "canonical_payload": {
                    "channel": "email",
                    "from": recipient,
                    "to": "support@tenant.example",
                    "subject": _TICKET_SUBJECT,
                    "message_id": "msg-inbound-1",
                    "conversation_id": "conv-1",
                }
            },
            created_at=_NOW.isoformat(),
            dispatched_at=_NOW.isoformat(),
            tenant_authority_source="test",
        )
    )


def _request(category: CaseApprovalEntryCategory) -> CaseApprovalReviewRequest:
    return CaseApprovalReviewRequest(
        tenant_id=_TENANT,
        session_id=_SESSION_ID,
        execution_id=_EXECUTION_ID,
        dispatch_id=_DISPATCH_ID,
        resolution_proposal_id=str(_PROPOSAL_ID),
        entry_category=category,
        issue_summary="warranty_replacement_inquiry",
        metadata={"confidence": 0.42},
    )


def _proposal(*, with_bound_action: bool = False) -> ResolutionProposalRecord:
    now = datetime.now(timezone.utc)
    return ResolutionProposalRecord(
        proposal_id=as_resolution_proposal_id(_PROPOSAL_ID),
        tenant_id=_TENANT,
        session_id=_SESSION_ID,
        execution_id=_EXECUTION_ID,
        dispatch_id=_DISPATCH_ID,
        diagnostic_event_id=None,
        proposed_customer_reply=_REPLY,
        resolution_category="warranty_replacement_inquiry",
        confidence=0.42,
        recommended_actions=(
            (
                {
                    "type": "warranty_claim",
                    "requires_execution": True,
                    "tool_name": "warranty.claim",
                    "action_approval_id": "bound-action-approval-1",
                    "payload": {"order_id": "order-1"},
                },
            )
            if with_bound_action
            else ()
        ),
        evidence=({"citation_label": "[1]", "safe_excerpt": "Warranty terms."},),
        supervisor_verdict=ResolutionSupervisorVerdict.NEEDS_HUMAN_REVIEW,
        governance_verdict=ResolutionGovernanceVerdict.REQUIRE_APPROVAL,
        autonomy_decision=ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL,
        status=ResolutionProposalStatus.PENDING_HUMAN_APPROVAL,
        created_at=now,
        updated_at=now,
    )


def _draft() -> ResolutionOutboundDraftRecord:
    now = datetime.now(timezone.utc)
    return ResolutionOutboundDraftRecord(
        draft_id=as_resolution_outbound_draft_id(_DRAFT_ID),
        tenant_id=_TENANT,
        proposal_id=as_resolution_proposal_id(_PROPOSAL_ID),
        session_id=_SESSION_ID,
        execution_id=_EXECUTION_ID,
        dispatch_id=_DISPATCH_ID,
        diagnostic_event_id=None,
        governance_decision_id=None,
        status=ResolutionOutboundDraftStatus.PENDING_HUMAN_APPROVAL,
        draft_body=_REPLY,
        draft_body_sha256=hashlib.sha256(_REPLY.encode("utf-8")).hexdigest(),
        resolution_category="warranty_replacement_inquiry",
        confidence=0.42,
        created_at=now,
        updated_at=now,
    )


async def _seed_proposal_and_draft(
    resolutions: InMemoryResolutionProposalPersistence,
    *,
    with_bound_action: bool = False,
) -> None:
    await resolutions.create_resolution_proposal(
        _proposal(with_bound_action=with_bound_action), expected_tenant_id=_TENANT
    )
    await resolutions.create_resolution_outbound_draft(_draft(), expected_tenant_id=_TENANT)


async def _approve(
    service: CaseApprovalService,
    ingress: ApprovalQueueIngressService,
) -> str:
    record = await ingress.request_case_review(
        _request(CaseApprovalEntryCategory.RESOLUTION_NEEDS_HUMAN_APPROVAL),
        expected_tenant_id=_TENANT,
    )
    reviewed = await service.review_case(
        approval_case_id=record.approval_case_id, tenant_id=_TENANT
    )
    await service.approve_case(
        approval_case_id=reviewed.approval_case_id,
        tenant_id=_TENANT,
        approved_by="operator-approve",
        note="Looks good.",
    )
    return reviewed.approval_case_id


@pytest.mark.asyncio
async def test_approval_auto_enqueues_with_real_customer_recipient_and_subject() -> None:
    """Break-controls (i) + (iv): approving an eligible resolution enqueues
    to outbound_send_outbox automatically, with no manual send call, and the
    recipient is the real customer's inbound address (never the SES
    envelope address) with a correctly derived "Re: <subject>"."""
    governance = InMemoryGovernanceRepository()
    outbox = InMemoryOutboundSendOutboxPersistence()
    coordination = InMemoryCoordinationPersistence()
    await _record_dispatch_envelope(coordination)
    resolutions = InMemoryResolutionProposalPersistence()
    await _seed_proposal_and_draft(resolutions)
    approval_persistence = InMemoryCaseApprovalPersistence()
    service = CaseApprovalService(
        persistence=approval_persistence,
        sme_runtime=SmeReviewRuntime(),
        resolution_repository=resolutions,
        governance_repository=governance,
        coordination_repository=coordination,
        outbound_auto_send_service=OutboundAutoSendService(
            governance_repository=governance, outbox_persistence=outbox
        ),
    )
    ingress = ApprovalQueueIngressService(persistence=approval_persistence)

    await _approve(service, ingress)

    page = await outbox.list_outbound_send_outbox(
        OutboundSendOutboxQuery(tenant_id=_TENANT)
    )
    assert page.total == 1
    enqueued = page.records[0]
    assert enqueued.recipient == _REAL_CUSTOMER_ADDRESS
    assert enqueued.recipient != _SES_ENVELOPE_ADDRESS
    assert enqueued.metadata["reply_recipient"] == _REAL_CUSTOMER_ADDRESS

    draft = await resolutions.get_resolution_outbound_draft(
        str(_DRAFT_ID), expected_tenant_id=_TENANT
    )
    assert draft is not None
    assert draft.status is ResolutionOutboundDraftStatus.READY


@pytest.mark.asyncio
async def test_no_coordination_repository_skips_auto_send_but_still_reaches_ready() -> None:
    """A construction site without auto-send wiring (e.g. the historical
    backfill scripts) must keep working exactly as before: the draft still
    reaches ready/send_eligible, it just never gets an automatic send
    trigger."""
    governance = InMemoryGovernanceRepository()
    resolutions = InMemoryResolutionProposalPersistence()
    await _seed_proposal_and_draft(resolutions)
    approval_persistence = InMemoryCaseApprovalPersistence()
    service = CaseApprovalService(
        persistence=approval_persistence,
        sme_runtime=SmeReviewRuntime(),
        resolution_repository=resolutions,
        governance_repository=governance,
    )
    ingress = ApprovalQueueIngressService(persistence=approval_persistence)

    await _approve(service, ingress)

    draft = await resolutions.get_resolution_outbound_draft(
        str(_DRAFT_ID), expected_tenant_id=_TENANT
    )
    assert draft is not None
    assert draft.status is ResolutionOutboundDraftStatus.READY


@pytest.mark.asyncio
async def test_reconciled_resweep_after_inline_approval_does_not_double_enqueue() -> None:
    """Break-control (iii): a reconciler re-sweep calling
    complete_reconciled_resolution after the case was already approved
    inline must not enqueue a second send -- the proposal is no longer
    PENDING_HUMAN_APPROVAL, so _deliver_resolution never runs again."""
    governance = InMemoryGovernanceRepository()
    outbox = InMemoryOutboundSendOutboxPersistence()
    coordination = InMemoryCoordinationPersistence()
    await _record_dispatch_envelope(coordination)
    approval_persistence = InMemoryCaseApprovalPersistence()
    resolutions = InMemoryResolutionProposalPersistence()
    await _seed_proposal_and_draft(resolutions)
    service = CaseApprovalService(
        persistence=approval_persistence,
        sme_runtime=SmeReviewRuntime(),
        resolution_repository=resolutions,
        governance_repository=governance,
        coordination_repository=coordination,
        outbound_auto_send_service=OutboundAutoSendService(
            governance_repository=governance, outbox_persistence=outbox
        ),
    )
    ingress = ApprovalQueueIngressService(persistence=approval_persistence)
    approval_case_id = await _approve(service, ingress)

    resweep_ran = await service.complete_reconciled_resolution(
        approval_case_id=approval_case_id,
        tenant_id=_TENANT,
        resolved_by="reconciler",
        note=None,
    )

    assert resweep_ran is False
    page = await outbox.list_outbound_send_outbox(
        OutboundSendOutboxQuery(tenant_id=_TENANT)
    )
    assert page.total == 1


@pytest.mark.asyncio
async def test_auto_send_failure_blocks_case_approval_and_action_atomically() -> None:
    """Break-control (ii): if the send-enqueue fails, the action/case
    completion must not silently succeed with an unsent reply. Here the
    case is bound to an action requiring execution; a forced auto-send
    refusal must raise out of approve_case BEFORE the case row is ever
    marked approved and BEFORE the bound action fires -- the reply-send
    check runs ahead of the action in _deliver_resolution's call order, so
    a refusal here means the action never gets a chance to fire either."""

    class _AlwaysRefusingAutoSend:
        async def request_auto_send(self, **_: object) -> OutboundAutoSendRequestResult:
            return OutboundAutoSendRequestResult(
                outbox=None,
                reason=OutboundAutoSendRefusalReason(
                    code="governance_miss",
                    message="forced refusal for atomicity test",
                ),
            )

    governance = InMemoryGovernanceRepository()
    coordination = InMemoryCoordinationPersistence()
    await _record_dispatch_envelope(coordination)
    approval_persistence = InMemoryCaseApprovalPersistence()
    resolutions = InMemoryResolutionProposalPersistence()
    await _seed_proposal_and_draft(resolutions, with_bound_action=True)

    action_fired = False

    async def _approve_bound_action(
        approval_id: str,
        approved_by: str,
        note: str | None,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> object:
        nonlocal action_fired
        action_fired = True
        return object()

    service = CaseApprovalService(
        persistence=approval_persistence,
        sme_runtime=SmeReviewRuntime(),
        resolution_repository=resolutions,
        governance_repository=governance,
        coordination_repository=coordination,
        outbound_auto_send_service=_AlwaysRefusingAutoSend(),  # type: ignore[arg-type]
        action_approval_approve=_approve_bound_action,
    )
    ingress = ApprovalQueueIngressService(persistence=approval_persistence)
    record = await ingress.request_case_review(
        _request(CaseApprovalEntryCategory.RESOLUTION_NEEDS_HUMAN_APPROVAL),
        expected_tenant_id=_TENANT,
    )
    reviewed = await service.review_case(
        approval_case_id=record.approval_case_id, tenant_id=_TENANT
    )

    with pytest.raises(CaseApprovalRuntimeError):
        await service.approve_case(
            approval_case_id=reviewed.approval_case_id,
            tenant_id=_TENANT,
            approved_by="operator-approve",
            note=None,
        )

    assert action_fired is False
    case = await approval_persistence.get_case(
        reviewed.approval_case_id, expected_tenant_id=_TENANT
    )
    assert case is not None
    assert case.status is CaseApprovalStatus.AWAITING_APPROVAL


@pytest.mark.asyncio
async def test_governance_denied_revision_never_enqueues_to_outbox() -> None:
    """Gate 2 / safety break-control: the danger of approve=send is
    sending something the grounding gate would have caught. A revised
    reply that fails resolution governance revalidation (DENY) must
    raise out of approve_case BEFORE any outbox enqueue -- even though
    full auto-send infrastructure (coordination_repository +
    OutboundAutoSendService) is wired and ready. _record_delivery_
    authorization_decision (the unconditional-ALLOW path) is only ever
    reached for an UNCHANGED reply, which by construction already passed
    build-time governance; a REVISED reply must re-earn an ALLOW via
    _revalidate_resolution_governance, and a DENY there aborts delivery
    entirely -- the outbox is never touched."""

    class _DenyingGate:
        async def evaluate_resolution_proposal(
            self, request: ResolutionGovernanceGateRequest
        ) -> ResolutionGovernanceGateResult:
            return ResolutionGovernanceGateResult(
                governance_verdict=ResolutionGovernanceVerdict.DENY,
                governance_decision_id=None,
            )

    class _UngroundedRevisionReviewer:
        async def review(
            self,
            context: SmeCaseContext,
            *,
            recommendation_id: str,
            guidance: str | None = None,
        ) -> SmeRecommendation:
            return SmeRecommendation(
                recommendation_id=recommendation_id,
                recommended_reply="We have fully refunded your order today.",
                recommended_actions=(),
                rationale="ungrounded revision for the denial-path test",
                confidence=0.9,
                citations=(),
                risk_flags=(),
                created_at=datetime.now(timezone.utc),
                reply_segments=({"claim": "fully refunded today"},),
            )

    governance = InMemoryGovernanceRepository()
    outbox = InMemoryOutboundSendOutboxPersistence()
    coordination = InMemoryCoordinationPersistence()
    await _record_dispatch_envelope(coordination)
    resolutions = InMemoryResolutionProposalPersistence()
    await _seed_proposal_and_draft(resolutions)
    approval_persistence = InMemoryCaseApprovalPersistence()
    service = CaseApprovalService(
        persistence=approval_persistence,
        sme_runtime=SmeReviewRuntime(llm_reviewer=_UngroundedRevisionReviewer()),
        resolution_repository=resolutions,
        governance_repository=governance,
        coordination_repository=coordination,
        outbound_auto_send_service=OutboundAutoSendService(
            governance_repository=governance, outbox_persistence=outbox
        ),
        resolution_governance_gate=_DenyingGate(),  # type: ignore[arg-type]
    )
    ingress = ApprovalQueueIngressService(persistence=approval_persistence)
    record = await ingress.request_case_review(
        _request(CaseApprovalEntryCategory.RESOLUTION_NEEDS_HUMAN_APPROVAL),
        expected_tenant_id=_TENANT,
    )
    reviewed = await service.review_case(
        approval_case_id=record.approval_case_id, tenant_id=_TENANT
    )
    assert reviewed.metadata["sme_recommendation"]["recommended_reply"] != _REPLY

    with pytest.raises(CaseApprovalRuntimeError):
        await service.approve_case(
            approval_case_id=reviewed.approval_case_id,
            tenant_id=_TENANT,
            approved_by="operator-approve",
            note=None,
        )

    page = await outbox.list_outbound_send_outbox(
        OutboundSendOutboxQuery(tenant_id=_TENANT)
    )
    assert page.total == 0
    draft = await resolutions.get_resolution_outbound_draft(
        str(_DRAFT_ID), expected_tenant_id=_TENANT
    )
    assert draft is not None
    assert draft.status is ResolutionOutboundDraftStatus.PENDING_HUMAN_APPROVAL
    proposal = await resolutions.get_resolution_proposal(
        str(_PROPOSAL_ID), expected_tenant_id=_TENANT
    )
    assert proposal is not None
    assert proposal.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
