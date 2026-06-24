"""Break-control coverage for the case-approval resolution reconciler.

Reproduces the live divergence: ``approve_case``/``reject_case`` fire the
case's bound action (durable, external side effect) and update the
case's own row in one request transaction; if the case's own update
never lands, the case is stuck in ``awaiting_approval`` forever even
though its bound action already resolved. These tests seed that exact
divergence directly against Postgres and assert the sweep
(``app.workers.case_approval_recovery_tasks``) closes it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import cast

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools.approvals import (
    ActionApprovalRecord,
    PostgresActionApprovalRepository,
)
from app.approvals.enums import CaseApprovalEntryCategory, CaseApprovalStatus
from app.approvals.persistence.postgres import PostgresCaseApprovalPersistence
from app.approvals.persistence.records import CaseApprovalRecord
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
)
from app.resolution.persistence import (
    PostgresResolutionProposalPersistence,
    ResolutionOutboundDraftQuery,
    ResolutionOutboundDraftRecord,
    ResolutionProposalRecord,
)
from app.session.enums import SessionLifecyclePhase, SessionScope
from app.session.identity import SessionId, SessionLineageId
from app.session.persistence import PostgresSessionPersistence, SessionRecord
from app.workers.case_approval_recovery_tasks import (
    reconcile_stale_case_approvals_runtime,
)
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]

_TENANT_ID = "tenant-case-approval-recovery"


@pytest.fixture
def pg_tenant_id() -> str:
    return _TENANT_ID


async def _ensure_tenant(session: AsyncSession, tenant_id: str) -> None:
    await session.execute(
        text(
            """
            INSERT INTO public.tenants (tenant_id)
            VALUES (:tenant_id)
            ON CONFLICT (tenant_id) DO NOTHING
            """
        ),
        {"tenant_id": tenant_id},
    )


async def _seed_session(session: AsyncSession, *, tenant_id: str) -> str:
    session_id = str(uuid.uuid4())
    sid = SessionId(uuid.UUID(session_id))
    now = datetime.now(timezone.utc)
    record = SessionRecord(
        session_id=sid,
        scope=SessionScope.TENANT,
        external_handle="case-approval-recovery-test",
        tenant_id=tenant_id,
        principal_id="principal-agent",
        opened_at=now,
        lifecycle_phase=SessionLifecyclePhase.ACTIVE,
        lifecycle_recorded_at=now,
        lifecycle_reason=None,
        lineage_id=SessionLineageId(uuid.UUID(session_id)),
        root_session_id=sid,
        parent_session_id=None,
        ancestor_session_ids=(),
        lineage_depth=0,
        sequence_head=-1,
        revision=0,
    )
    await PostgresSessionPersistence(session).save_session(record)
    return session_id


async def _seed_action(
    session: AsyncSession,
    *,
    tenant_id: str,
    status: str = "pending",
) -> ActionApprovalRecord:
    session_id = await _seed_session(session, tenant_id=tenant_id)
    repo = PostgresActionApprovalRepository(session)
    record = ActionApprovalRecord(
        approval_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        session_id=session_id,
        execution_id=None,
        tool_name="refund.request",
        idempotency_key=str(uuid.uuid4()),
        payload_json={},
        governance_decision_id=None,
        status="pending",
    )
    created = await repo.create_pending_approval(record, expected_tenant_id=tenant_id)
    if status == "pending":
        return created
    resolved = await repo.resolve_approval(
        created.approval_id,
        expected_tenant_id=tenant_id,
        status=status,
        resolved_at=datetime.now(timezone.utc),
        resolved_by="manager-jane",
        resolution_note=f"Resolved as {status} by manager-jane.",
        metadata={},
    )
    assert resolved is not None
    return resolved


async def _seed_case(
    session: AsyncSession,
    *,
    tenant_id: str,
    action_approval_id: str,
    resolution_proposal_id: str | None = None,
) -> CaseApprovalRecord:
    persistence = PostgresCaseApprovalPersistence(session)
    record = CaseApprovalRecord(
        approval_case_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        session_id=None,
        execution_id=None,
        dispatch_id=None,
        entry_category=CaseApprovalEntryCategory.REFUND_WARRANTY,
        status=CaseApprovalStatus.AWAITING_APPROVAL,
        requested_at=datetime.now(timezone.utc),
        dedup_key=str(uuid.uuid4()),
        recommended_action={"action_approval_id": action_approval_id},
        resolution_proposal_id=resolution_proposal_id,
    )
    return await persistence.create_case(record, expected_tenant_id=tenant_id)


async def _seed_proposal_and_draft(
    session: AsyncSession, *, tenant_id: str
) -> str:
    """Seed a resolution proposal + its outbound draft, both still
    ``pending_human_approval`` -- the state a case's bound reply sits in
    until something delivers it. Returns the proposal id."""
    resolutions = PostgresResolutionProposalPersistence(session)
    proposal_id = as_resolution_proposal_id(str(uuid.uuid4()))
    draft_id = as_resolution_outbound_draft_id(str(uuid.uuid4()))
    now = datetime.now(timezone.utc)
    seeded_session_id = await _seed_session(session, tenant_id=tenant_id)
    execution_id = str(uuid.uuid4())
    dispatch_id = str(uuid.uuid4())
    await session.execute(
        text(
            """
            INSERT INTO public.execution_records (
                execution_id, kind, dispatch_id, session_id, tenant_id,
                state, attempt_count, requested_at, result, metadata
            )
            VALUES (
                :execution_id, 'diagnostic_agent', :dispatch_id,
                :session_id, :tenant_id, 'requested', 0,
                :requested_at, '{}'::jsonb, '{}'::jsonb
            )
            ON CONFLICT (tenant_id, dispatch_id, kind) DO NOTHING
            """
        ),
        {
            "execution_id": uuid.UUID(execution_id),
            "dispatch_id": dispatch_id,
            "session_id": seeded_session_id,
            "tenant_id": tenant_id,
            "requested_at": now,
        },
    )
    await resolutions.create_resolution_proposal(
        ResolutionProposalRecord(
            proposal_id=proposal_id,
            tenant_id=tenant_id,
            session_id=seeded_session_id,
            execution_id=execution_id,
            dispatch_id=dispatch_id,
            diagnostic_event_id=None,
            proposed_customer_reply="We can help review the warranty claim.",
            resolution_category="warranty_replacement_inquiry",
            confidence=0.42,
            recommended_actions=(
                {
                    "type": "warranty_claim",
                    "requires_execution": True,
                    "tool_name": "warranty.claim",
                    "payload": {"order_id": "order-1", "product_sku": "sku-1"},
                },
            ),
            evidence=(
                {"citation_label": "[1]", "safe_excerpt": "Warranty terms."},
            ),
            supervisor_verdict=ResolutionSupervisorVerdict.NEEDS_HUMAN_REVIEW,
            governance_verdict=ResolutionGovernanceVerdict.REQUIRE_APPROVAL,
            autonomy_decision=ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL,
            status=ResolutionProposalStatus.PENDING_HUMAN_APPROVAL,
            created_at=now,
            updated_at=now,
        ),
        expected_tenant_id=tenant_id,
    )
    await resolutions.create_resolution_outbound_draft(
        ResolutionOutboundDraftRecord(
            draft_id=draft_id,
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            session_id=str(uuid.uuid4()),
            execution_id=str(uuid.uuid4()),
            dispatch_id=str(uuid.uuid4()),
            diagnostic_event_id=None,
            governance_decision_id=None,
            status=ResolutionOutboundDraftStatus.PENDING_HUMAN_APPROVAL,
            draft_body="We can help review the warranty claim.",
            draft_body_sha256="a" * 64,
            resolution_category="warranty_replacement_inquiry",
            confidence=0.42,
            created_at=now,
            updated_at=now,
        ),
        expected_tenant_id=tenant_id,
    )
    return str(proposal_id)


@pytest.mark.asyncio
async def test_reconciles_stuck_case_to_match_approved_action(
    pg_session: AsyncSession,
    pg_tenant_id: str,
) -> None:
    await _ensure_tenant(pg_session, pg_tenant_id)
    action = await _seed_action(pg_session, tenant_id=pg_tenant_id, status="approved")
    case = await _seed_case(
        pg_session,
        tenant_id=pg_tenant_id,
        action_approval_id=action.approval_id,
    )

    result = await reconcile_stale_case_approvals_runtime(
        limit=100, session=pg_session
    )

    assert result["reconciled_count"] == 1
    reconciled = cast("list[dict[str, object]]", result["reconciled"])[0]
    assert reconciled["approval_case_id"] == case.approval_case_id
    assert reconciled["new_status"] == CaseApprovalStatus.APPROVED.value
    assert reconciled["resolved_by"] == "manager-jane"

    persistence = PostgresCaseApprovalPersistence(pg_session)
    saved = await persistence.get_case(
        case.approval_case_id, expected_tenant_id=pg_tenant_id
    )
    assert saved is not None
    assert saved.status == CaseApprovalStatus.APPROVED
    assert saved.resolved_by == "manager-jane"
    assert saved.resolved_at == action.resolved_at


@pytest.mark.asyncio
async def test_denied_action_drives_case_to_rejected_not_resolved(
    pg_session: AsyncSession,
    pg_tenant_id: str,
) -> None:
    await _ensure_tenant(pg_session, pg_tenant_id)
    action = await _seed_action(pg_session, tenant_id=pg_tenant_id, status="denied")
    case = await _seed_case(
        pg_session,
        tenant_id=pg_tenant_id,
        action_approval_id=action.approval_id,
    )

    result = await reconcile_stale_case_approvals_runtime(
        limit=100, session=pg_session
    )

    assert result["reconciled_count"] == 1
    reconciled = cast("list[dict[str, object]]", result["reconciled"])[0]
    assert reconciled["new_status"] == CaseApprovalStatus.REJECTED.value

    persistence = PostgresCaseApprovalPersistence(pg_session)
    saved = await persistence.get_case(
        case.approval_case_id, expected_tenant_id=pg_tenant_id
    )
    assert saved is not None
    assert saved.status == CaseApprovalStatus.REJECTED


@pytest.mark.asyncio
async def test_case_with_still_pending_action_is_left_untouched(
    pg_session: AsyncSession,
    pg_tenant_id: str,
) -> None:
    await _ensure_tenant(pg_session, pg_tenant_id)
    action = await _seed_action(pg_session, tenant_id=pg_tenant_id, status="pending")
    case = await _seed_case(
        pg_session,
        tenant_id=pg_tenant_id,
        action_approval_id=action.approval_id,
    )

    result = await reconcile_stale_case_approvals_runtime(
        limit=100, session=pg_session
    )

    assert result["reconciled_count"] == 0
    assert result["skipped_pending_count"] == 1

    persistence = PostgresCaseApprovalPersistence(pg_session)
    saved = await persistence.get_case(
        case.approval_case_id, expected_tenant_id=pg_tenant_id
    )
    assert saved is not None
    assert saved.status == CaseApprovalStatus.AWAITING_APPROVAL
    assert saved.resolved_at is None


@pytest.mark.asyncio
async def test_rerun_after_reconciliation_is_a_no_op(
    pg_session: AsyncSession,
    pg_tenant_id: str,
) -> None:
    await _ensure_tenant(pg_session, pg_tenant_id)
    action = await _seed_action(pg_session, tenant_id=pg_tenant_id, status="approved")
    await _seed_case(
        pg_session,
        tenant_id=pg_tenant_id,
        action_approval_id=action.approval_id,
    )

    first = await reconcile_stale_case_approvals_runtime(limit=100, session=pg_session)
    assert first["reconciled_count"] == 1

    second = await reconcile_stale_case_approvals_runtime(
        limit=100, session=pg_session
    )

    assert second["reconciled_count"] == 0
    assert second["candidates_scanned"] == 0


@pytest.mark.asyncio
async def test_reconciled_approval_also_delivers_the_bound_reply(
    pg_session: AsyncSession,
    pg_tenant_id: str,
) -> None:
    """The regression this sweep must not reintroduce: a reconciled case
    that only flips status while its bound reply stays
    ``pending_human_approval`` forever, never reaching ``outbound.send``."""
    await _ensure_tenant(pg_session, pg_tenant_id)
    action = await _seed_action(pg_session, tenant_id=pg_tenant_id, status="approved")
    proposal_id = await _seed_proposal_and_draft(pg_session, tenant_id=pg_tenant_id)
    case = await _seed_case(
        pg_session,
        tenant_id=pg_tenant_id,
        action_approval_id=action.approval_id,
        resolution_proposal_id=proposal_id,
    )

    result = await reconcile_stale_case_approvals_runtime(
        limit=100, session=pg_session
    )

    assert result["reconciled_count"] == 1
    assert result["delivered_count"] == 1
    reconciled = cast("list[dict[str, object]]", result["reconciled"])[0]
    assert reconciled["delivered"] is True
    # Attributed to the real approver of the bound action, never to the
    # sweep itself or "system".
    assert reconciled["resolved_by"] == "manager-jane"

    case_persistence = PostgresCaseApprovalPersistence(pg_session)
    saved_case = await case_persistence.get_case(
        case.approval_case_id, expected_tenant_id=pg_tenant_id
    )
    assert saved_case is not None
    assert saved_case.status == CaseApprovalStatus.APPROVED
    assert saved_case.governance_decision_id is not None

    resolutions = PostgresResolutionProposalPersistence(pg_session)
    saved_proposal = await resolutions.get_resolution_proposal(
        proposal_id, expected_tenant_id=pg_tenant_id
    )
    assert saved_proposal is not None
    assert saved_proposal.status == ResolutionProposalStatus.SEND_ELIGIBLE
    assert saved_proposal.governance_decision_id is not None
    # The case-approval decision authorizes the CASE; the proposal/draft
    # must instead reference a dedicated delivery-authorization decision
    # (carrying proposal_id + proposed_reply_sha256, which the email/
    # whatsapp send-time governance check requires), never the case's
    # own decision.
    assert str(saved_proposal.governance_decision_id) != saved_case.governance_decision_id

    saved_draft = await resolutions.list_resolution_outbound_drafts(
        ResolutionOutboundDraftQuery(proposal_id=proposal_id),
        expected_tenant_id=pg_tenant_id,
    )
    assert len(saved_draft.items) == 1
    assert saved_draft.items[0].status == ResolutionOutboundDraftStatus.READY
    assert saved_draft.items[0].governance_decision_id == saved_proposal.governance_decision_id


@pytest.mark.asyncio
async def test_reconciled_rejection_does_not_deliver(
    pg_session: AsyncSession,
    pg_tenant_id: str,
) -> None:
    """Break-control: a case with no APPROVED bound action is never
    delivered, even when it carries a bound resolution proposal."""
    await _ensure_tenant(pg_session, pg_tenant_id)
    action = await _seed_action(pg_session, tenant_id=pg_tenant_id, status="denied")
    proposal_id = await _seed_proposal_and_draft(pg_session, tenant_id=pg_tenant_id)
    await _seed_case(
        pg_session,
        tenant_id=pg_tenant_id,
        action_approval_id=action.approval_id,
        resolution_proposal_id=proposal_id,
    )

    result = await reconcile_stale_case_approvals_runtime(
        limit=100, session=pg_session
    )

    assert result["reconciled_count"] == 1
    reconciled = cast("list[dict[str, object]]", result["reconciled"])[0]
    assert reconciled["new_status"] == CaseApprovalStatus.REJECTED.value
    assert reconciled["delivered"] is False

    resolutions = PostgresResolutionProposalPersistence(pg_session)
    saved_proposal = await resolutions.get_resolution_proposal(
        proposal_id, expected_tenant_id=pg_tenant_id
    )
    assert saved_proposal is not None
    assert saved_proposal.status == ResolutionProposalStatus.PENDING_HUMAN_APPROVAL


@pytest.mark.asyncio
async def test_rerun_after_reconciled_delivery_does_not_redeliver(
    pg_session: AsyncSession,
    pg_tenant_id: str,
) -> None:
    """Idempotency: a second sweep over an already-delivered case must not
    re-run delivery (no double-send risk if the reply were truly
    transmitted downstream of ``send_eligible``/``ready``)."""
    await _ensure_tenant(pg_session, pg_tenant_id)
    action = await _seed_action(pg_session, tenant_id=pg_tenant_id, status="approved")
    proposal_id = await _seed_proposal_and_draft(pg_session, tenant_id=pg_tenant_id)
    await _seed_case(
        pg_session,
        tenant_id=pg_tenant_id,
        action_approval_id=action.approval_id,
        resolution_proposal_id=proposal_id,
    )

    first = await reconcile_stale_case_approvals_runtime(limit=100, session=pg_session)
    assert first["delivered_count"] == 1

    second = await reconcile_stale_case_approvals_runtime(
        limit=100, session=pg_session
    )

    assert second["reconciled_count"] == 0
    assert second["candidates_scanned"] == 0

    resolutions = PostgresResolutionProposalPersistence(pg_session)
    saved_proposal = await resolutions.get_resolution_proposal(
        proposal_id, expected_tenant_id=pg_tenant_id
    )
    assert saved_proposal is not None
    assert saved_proposal.status == ResolutionProposalStatus.SEND_ELIGIBLE
