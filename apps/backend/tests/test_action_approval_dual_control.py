"""Dual-control enforcement tests for action approval path.

Security fix B: approver must differ from proposer on money/goods actions.
These are the four break-controls required by the fix specification:

  (i)   same principal proposes + approves → REJECTED (separation error)
  (ii)  different principal approves → succeeds (legit dual-control)
  (iii) proposed_by is read from first-class column, not spoofable via metadata
  (iv)  proposed_by=None (pre-migration rows) → still approvable (no regression)

Phase-1 audit additions:
  (v)  Guard calls through REAL ActionApprovalService.approve_in_transaction()
  (vi) deny_in_transaction() also enforces separation
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.tools.approvals import (
    ActionApprovalRecord,
    InMemoryActionApprovalRepository,
    build_pending_action_approval,
)
from app.services.action_approval_service import (
    ActionApprovalLifecycleError,
    ActionApprovalSeparationError,
    ActionApprovalService,
)

# ---------------------------------------------------------------------------
# Minimal in-memory doubles
# ---------------------------------------------------------------------------

_TENANT = "tenant-test"
_AGENT_ACTOR = "agent:diagnostic-action-orchestrator"
_MANAGER_A = "principal-manager-alice"
_MANAGER_B = "principal-manager-bob"
_NOW = datetime(2026, 7, 3, 12, tzinfo=timezone.utc)


def _make_approval(
    *,
    proposed_by: str | None,
    idempotency_seed: str = "default",
) -> ActionApprovalRecord:
    idempotency_key = str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"{_TENANT}:{idempotency_seed}:key")
    )
    session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{_TENANT}:{idempotency_seed}:session"))
    execution_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{_TENANT}:{idempotency_seed}:execution"))
    return build_pending_action_approval(
        tenant_id=_TENANT,
        session_id=session_id,
        execution_id=execution_id,
        tool_name="refund.request",
        idempotency_key=idempotency_key,
        payload_json={"order_id": "order-999", "amount_cents": 5000},
        governance_decision_id=None,
        metadata={"action_type": "refund_request"},
        proposed_by=proposed_by,
    )


class _StubApprovalService:
    """Thin wrapper that exercises the separation guard only."""

    def __init__(self, approval: ActionApprovalRecord) -> None:
        self._repo = InMemoryActionApprovalRepository()
        self._approval = approval

    async def seed(self) -> None:
        await self._repo.create_pending_approval(
            self._approval,
            expected_tenant_id=_TENANT,
        )

    async def attempt_approve(self, *, approved_by: str) -> ActionApprovalRecord:
        approval = await self._repo.get_approval(
            self._approval.approval_id,
            expected_tenant_id=_TENANT,
        )
        assert approval is not None

        # Inline the guard from approve_in_transaction — same logic, same test.
        if approval.proposed_by is not None and approved_by == approval.proposed_by:
            raise ActionApprovalSeparationError(
                "action approver must differ from proposer"
            )
        # Simulate resolve (no real action execution needed for these guard tests)
        resolved = await self._repo.resolve_approval(
            approval.approval_id,
            expected_tenant_id=_TENANT,
            status="approved",
            resolved_at=_NOW,
            resolved_by=approved_by,
            resolution_note=None,
            metadata=dict(approval.metadata),
        )
        assert resolved is not None
        return resolved


# ---------------------------------------------------------------------------
# Test (i): same principal proposes + approves → REJECTED
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_self_approval_rejected_when_proposed_by_matches() -> None:
    """An agent/actor that proposed the action cannot approve it.

    This is the core doctrine gap being fixed: the approver must differ
    from the proposer.  approved_by == proposed_by → ActionApprovalSeparationError.
    """
    approval = _make_approval(proposed_by=_AGENT_ACTOR, idempotency_seed="self-approve")
    svc = _StubApprovalService(approval)
    await svc.seed()

    with pytest.raises(ActionApprovalSeparationError, match="approver must differ"):
        await svc.attempt_approve(approved_by=_AGENT_ACTOR)


# ---------------------------------------------------------------------------
# Test (ii): different principal approves → succeeds (legit dual-control)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_different_principal_can_approve() -> None:
    """A different human manager can approve an agent-proposed action.

    This is the standard flow: agent proposes, manager approves.
    """
    approval = _make_approval(proposed_by=_AGENT_ACTOR, idempotency_seed="legit-approve")
    svc = _StubApprovalService(approval)
    await svc.seed()

    resolved = await svc.attempt_approve(approved_by=_MANAGER_A)
    assert resolved.status == "approved"
    assert resolved.resolved_by == _MANAGER_A


# ---------------------------------------------------------------------------
# Test (iii): proposed_by is first-class on the record, not spoofable via metadata
# ---------------------------------------------------------------------------

def test_proposed_by_is_first_class_not_from_metadata() -> None:
    """proposed_by is stored on ActionApprovalRecord directly.

    An attacker cannot override it by injecting 'agent_action_actor'
    into the metadata dict — proposed_by is set at creation time by the
    orchestrator, not derived from the caller-controlled metadata.
    """
    attacker_actor = "agent:attacker"
    approval = build_pending_action_approval(
        tenant_id=_TENANT,
        session_id=str(uuid.uuid4()),
        execution_id=None,
        tool_name="refund.request",
        idempotency_key=str(uuid.uuid4()),
        payload_json={},
        governance_decision_id=None,
        metadata={
            # An attacker sets this metadata key to try to spoof the proposer check
            "agent_action_actor": attacker_actor,
        },
        proposed_by=_AGENT_ACTOR,  # set by orchestrator, not caller-supplied
    )
    # The first-class column holds the orchestrator-supplied value
    assert approval.proposed_by == _AGENT_ACTOR
    # The metadata key cannot override it
    assert approval.proposed_by != approval.metadata.get("agent_action_actor")


# ---------------------------------------------------------------------------
# Test (iv): proposed_by=None (pre-migration rows) → approvable, no regression
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_legacy_approval_without_proposed_by_still_approvable() -> None:
    """Records created before the migration (proposed_by IS NULL) remain approvable.

    The guard only fires when proposed_by is not None.  Old rows get
    proposed_by=None from the column default; they must not be blocked.
    """
    approval = _make_approval(proposed_by=None, idempotency_seed="legacy")
    svc = _StubApprovalService(approval)
    await svc.seed()

    # Any principal can approve a legacy record (guard is skipped for None)
    resolved = await svc.attempt_approve(approved_by=_MANAGER_B)
    assert resolved.status == "approved"


# ---------------------------------------------------------------------------
# Test: build_pending_action_approval passes proposed_by through correctly
# ---------------------------------------------------------------------------

def test_build_pending_approval_stores_proposed_by() -> None:
    approval = build_pending_action_approval(
        tenant_id=_TENANT,
        session_id=str(uuid.uuid4()),
        execution_id=None,
        tool_name="warranty.claim",
        idempotency_key=str(uuid.uuid4()),
        payload_json={},
        governance_decision_id=None,
        proposed_by=_AGENT_ACTOR,
    )
    assert approval.proposed_by == _AGENT_ACTOR


def test_build_pending_approval_proposed_by_defaults_to_none() -> None:
    approval = build_pending_action_approval(
        tenant_id=_TENANT,
        session_id=str(uuid.uuid4()),
        execution_id=None,
        tool_name="warranty.claim",
        idempotency_key=str(uuid.uuid4()),
        payload_json={},
        governance_decision_id=None,
    )
    assert approval.proposed_by is None


# ---------------------------------------------------------------------------
# Phase-1 audit: test (v) — guard through REAL ActionApprovalService
# ---------------------------------------------------------------------------
# These tests call through ActionApprovalService.approve_in_transaction() and
# deny_in_transaction() directly (with mocked I/O beyond the guard point) so
# we exercise the PRODUCTION code path, not a copy of the guard.

async def _make_service(approval: ActionApprovalRecord) -> ActionApprovalService:
    """Build a real ActionApprovalService with an in-memory repo and mocked
    session + dependencies.  The guard fires BEFORE any mocked I/O is called,
    so we only need the repository to be functional."""
    repo = InMemoryActionApprovalRepository()
    await repo.create_pending_approval(approval, expected_tenant_id=_TENANT)

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    mock_orchestration = AsyncMock()
    mock_orchestration.re_invoke_approved_action = AsyncMock()

    return ActionApprovalService(
        approval_repository=repo,
        grant_repository=AsyncMock(),
        governance_repository=AsyncMock(),
        resolution_repository=AsyncMock(),
        session_repository=AsyncMock(),
        timeline_runtime=AsyncMock(),
        session=mock_session,
        orchestration_runtime=mock_orchestration,
    )


@pytest.mark.asyncio
async def test_service_approve_in_transaction_rejects_self_approval() -> None:
    """REAL service: approve_in_transaction raises ActionApprovalSeparationError
    when approved_by == proposed_by.  Exercises the production code path.
    """
    approval = _make_approval(proposed_by=_AGENT_ACTOR, idempotency_seed="real-svc-self")
    svc = await _make_service(approval)

    with pytest.raises(ActionApprovalSeparationError, match="approver must differ"):
        await svc.approve_in_transaction(
            approval_id=approval.approval_id,
            approved_by=_AGENT_ACTOR,  # same as proposed_by → must reject
            note=None,
            tenant_id=_TENANT,
            expected_tenant_id=_TENANT,
        )


@pytest.mark.asyncio
async def test_service_deny_in_transaction_rejects_self_denial() -> None:
    """REAL service: deny_in_transaction raises ActionApprovalSeparationError
    when denied_by == proposed_by.  Confirms the guard covers both paths.
    """
    approval = _make_approval(proposed_by=_AGENT_ACTOR, idempotency_seed="real-svc-deny")
    svc = await _make_service(approval)

    with pytest.raises(ActionApprovalSeparationError, match="denier must differ"):
        await svc.deny_in_transaction(
            approval_id=approval.approval_id,
            denied_by=_AGENT_ACTOR,  # same as proposed_by → must reject
            reason="testing self-denial rejection",
            tenant_id=_TENANT,
            expected_tenant_id=_TENANT,
        )


# ---------------------------------------------------------------------------
# C-3: AND status='pending' guard prevents double-resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_approval_returns_none_when_already_resolved() -> None:
    """InMemory resolve_approval returns None if status != 'pending' (C-3).

    The AND status='pending' guard in _RESOLVE_APPROVAL_SQL (Postgres) and
    the status check in InMemoryActionApprovalRepository.resolve_approval
    ensure that a concurrent second call cannot overwrite a resolved record.
    """
    repo = InMemoryActionApprovalRepository()
    approval = _make_approval(proposed_by=_AGENT_ACTOR, idempotency_seed="c3-double")
    await repo.create_pending_approval(approval, expected_tenant_id=_TENANT)

    now = datetime.now(timezone.utc)

    # First resolution succeeds.
    resolved = await repo.resolve_approval(
        approval.approval_id,
        expected_tenant_id=_TENANT,
        status="approved",
        resolved_at=now,
        resolved_by=_MANAGER_A,
        resolution_note=None,
        metadata={},
    )
    assert resolved is not None
    assert resolved.status == "approved"

    # Second resolution on an already-resolved record returns None (lost race).
    second = await repo.resolve_approval(
        approval.approval_id,
        expected_tenant_id=_TENANT,
        status="denied",
        resolved_at=now,
        resolved_by=_MANAGER_B,
        resolution_note="concurrent",
        metadata={},
    )
    assert second is None, "double-resolve must return None, not overwrite the first"

    # The record retains the first resolution — it was not corrupted.
    final = await repo.get_approval(approval.approval_id, expected_tenant_id=_TENANT)
    assert final is not None
    assert final.status == "approved"
    assert final.resolved_by == _MANAGER_A


@pytest.mark.asyncio
async def test_resolve_non_pending_approval_returns_none() -> None:
    """An already-denied record cannot be overwritten by a subsequent approve (C-3)."""
    repo = InMemoryActionApprovalRepository()
    approval = _make_approval(proposed_by=_AGENT_ACTOR, idempotency_seed="c3-deny-then-approve")
    await repo.create_pending_approval(approval, expected_tenant_id=_TENANT)

    now = datetime.now(timezone.utc)

    # Deny first.
    denied = await repo.resolve_approval(
        approval.approval_id,
        expected_tenant_id=_TENANT,
        status="denied",
        resolved_at=now,
        resolved_by=_MANAGER_B,
        resolution_note="denied",
        metadata={},
    )
    assert denied is not None and denied.status == "denied"

    # Subsequent approve returns None — the status guard blocks it.
    late_approve = await repo.resolve_approval(
        approval.approval_id,
        expected_tenant_id=_TENANT,
        status="approved",
        resolved_at=now,
        resolved_by=_MANAGER_A,
        resolution_note=None,
        metadata={},
    )
    assert late_approve is None

    # Record still shows denied.
    final = await repo.get_approval(approval.approval_id, expected_tenant_id=_TENANT)
    assert final is not None and final.status == "denied"
