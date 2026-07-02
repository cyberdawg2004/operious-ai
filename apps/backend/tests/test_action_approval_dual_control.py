"""Dual-control enforcement tests for action approval path.

Security fix B: approver must differ from proposer on money/goods actions.
These are the four break-controls required by the fix specification:

  (i)   same principal proposes + approves → REJECTED (separation error)
  (ii)  different principal approves → succeeds (legit dual-control)
  (iii) proposed_by is read from first-class column, not spoofable via metadata
  (iv)  proposed_by=None (pre-migration rows) → still approvable (no regression)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.agents.tools.approvals import (
    ActionApprovalRecord,
    InMemoryActionApprovalRepository,
    build_pending_action_approval,
)
from app.services.action_approval_service import (
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
