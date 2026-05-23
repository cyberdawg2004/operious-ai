"""Phase G escalation outbox recovery coverage."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.escalation import (
    EscalationAgentRuntime,
    EscalationOutboxStatus,
    InMemoryEscalationPersistence,
)
from app.governance.persistence import (
    GovernanceDecisionRecord,
    InMemoryGovernanceRepository,
)
from app.session.enums import SessionLifecyclePhase, SessionScope
from app.session.identity import SessionId, SessionLineageId
from app.session.persistence import InMemorySessionPersistence, SessionRecord

_TENANT = "tenant-phase-g"
_SESSION_ID = "00000000-0000-0000-0000-00000000f001"
_DENY_ID = "00000000-0000-0000-0000-00000000f002"
_NOW = datetime(2026, 5, 23, 8, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_escalation_outbox_recovers_stuck_publish() -> None:
    runtime, store = await _runtime()
    escalation = await runtime.create_for_governance_denial(
        governance_decision_id=_DENY_ID,
        expected_tenant_id=_TENANT,
    )
    outbox = await runtime.ensure_outbox_for_escalation(
        escalation,
        expected_tenant_id=_TENANT,
    )

    claim = await runtime.claim_outbox_for_escalation(
        escalation_id=escalation.escalation_id,
        publisher_id="test:publisher-a",
        expected_tenant_id=_TENANT,
    )
    assert claim.claimed is True
    assert claim.outbox is not None
    assert claim.outbox.status is EscalationOutboxStatus.PUBLISHING

    sweep = await runtime.reconcile_stale_outbox_records(
        stale_before=datetime.now(timezone.utc) + timedelta(seconds=1),
        expected_tenant_id=_TENANT,
    )

    assert len(sweep.requeued) == 1
    recovered = sweep.requeued[0]
    assert recovered.outbox_id == outbox.outbox_id
    assert recovered.status is EscalationOutboxStatus.PENDING
    assert recovered.claimed_at is None
    assert recovered.last_error == "stale_publishing_claim"

    reclaimed = await runtime.claim_outbox_for_escalation(
        escalation_id=escalation.escalation_id,
        publisher_id="test:publisher-b",
        expected_tenant_id=_TENANT,
    )
    assert reclaimed.claimed is True
    assert reclaimed.outbox is not None
    assert reclaimed.outbox.republish_count == 2
    assert await store.get_escalation_outbox_by_escalation(
        escalation.escalation_id,
        expected_tenant_id=_TENANT,
    ) == reclaimed.outbox


async def _runtime() -> tuple[EscalationAgentRuntime, InMemoryEscalationPersistence]:
    escalations = InMemoryEscalationPersistence()
    governance = InMemoryGovernanceRepository()
    sessions = InMemorySessionPersistence()
    await sessions.save_session(_session())
    await governance.record_decision(_decision())
    return (
        EscalationAgentRuntime(
            escalation_persistence=escalations,
            governance_repository=governance,
            session_persistence=sessions,
        ),
        escalations,
    )


def _session() -> SessionRecord:
    sid = SessionId(uuid.UUID(_SESSION_ID))
    return SessionRecord(
        session_id=sid,
        scope=SessionScope.TENANT,
        external_handle="ticket-phase-g",
        tenant_id=_TENANT,
        principal_id="principal-agent",
        opened_at=_NOW,
        lifecycle_phase=SessionLifecyclePhase.ACTIVE,
        lifecycle_recorded_at=_NOW,
        lifecycle_reason=None,
        lineage_id=SessionLineageId(uuid.UUID(_SESSION_ID)),
        root_session_id=sid,
        parent_session_id=None,
        ancestor_session_ids=(),
        lineage_depth=0,
        sequence_head=0,
        revision=1,
    )


def _decision() -> GovernanceDecisionRecord:
    return GovernanceDecisionRecord(
        decision_id=_DENY_ID,
        decision="deny",
        stage="pre_execution",
        policy_chain_id="phase.g.test",
        reason="deny: phase-g fixture",
        decided_at=_NOW.isoformat(),
        correlation_id="corr-phase-g",
        request_id="req-phase-g",
        tenant_id=_TENANT,
        subject_kind="communication",
        metadata={"session_id": _SESSION_ID},
    )
