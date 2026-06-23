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
    )
    return await persistence.create_case(record, expected_tenant_id=tenant_id)


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
