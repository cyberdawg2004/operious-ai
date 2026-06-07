"""Phase 3-C EscalationAgent runtime tests."""

from __future__ import annotations

import inspect
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.escalation import (
    EscalationAgentRuntime,
    EscalationHandoffKind,
    EscalationPriority,
    EscalationQuery,
    EscalationRuntimeError,
    EscalationStatus,
    InMemoryEscalationPersistence,
    derive_escalation_id,
    derive_escalation_override_decision_id,
)
from app.governance.persistence import (
    DecisionQuery,
    GovernanceDecisionRecord,
    InMemoryGovernanceRepository,
    PolicyEvaluationResultRecord,
)
from app.session.enums import SessionEventKind, SessionLifecyclePhase, SessionScope
from app.session.identity import (
    SessionId,
    SessionLineageId,
)
from app.session.persistence import (
    InMemorySessionPersistence,
    SessionEventQuery,
    SessionRecord,
)

_TENANT = "tenant-acme"
_OTHER_TENANT = "tenant-other"
_SESSION_ID = "00000000-0000-0000-0000-000000003c01"
_DENY_ID = "00000000-0000-0000-0000-000000003c02"
_ALLOW_ID = "00000000-0000-0000-0000-000000003c03"
_ESCALATE_ID = "00000000-0000-0000-0000-000000003c04"
_CRISIS_DENY_ID = "00000000-0000-0000-0000-000000003c05"
_NOW = datetime(2026, 5, 22, 10, tzinfo=timezone.utc)


def _session(*, tenant_id: str = _TENANT) -> SessionRecord:
    sid = SessionId(uuid.UUID(_SESSION_ID))
    return SessionRecord(
        session_id=sid,
        scope=SessionScope.TENANT,
        external_handle="ticket-123",
        tenant_id=tenant_id,
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
        sequence_head=-1,
        revision=1,
    )


def _decision(
    *,
    decision_id: str = _DENY_ID,
    decision: str = "deny",
    tenant_id: str = _TENANT,
    session_id: str | None = _SESSION_ID,
) -> GovernanceDecisionRecord:
    metadata = {"session_id": session_id} if session_id is not None else {}
    return GovernanceDecisionRecord(
        decision_id=decision_id,
        decision=decision,
        stage="pre_execution",
        policy_chain_id="test.chain",
        reason="deny: policy.fixture",
        decided_at=_NOW.isoformat(),
        correlation_id="corr-3c",
        request_id="req-3c",
        tenant_id=tenant_id,
        subject_kind="communication",
        metadata=metadata,
    )


def _grounding_decision() -> GovernanceDecisionRecord:
    trace = {
        "schema_version": "2.1",
        "status": "ungrounded",
        "approved_knowledge_found": [{"rank": 1}],
        "ungrounded_claims": [
            {
                "claim": "Unsupported replacement promise.",
                "reason": "uncited_claim",
                "citation_ranks": [],
            }
        ],
    }
    handoff = {
        "ticket_no": _SESSION_ID,
        "issue": "Customer reports a charging issue.",
        "escalation": "ungrounded_claim",
        "description": "Generated reply could not be grounded.",
        "recommendation": "Human reviewer should answer from approved SOPs.",
        "grounding_trace": trace,
    }
    return GovernanceDecisionRecord(
        decision_id=_DENY_ID,
        decision="deny",
        stage="pre_execution",
        policy_chain_id="resolution.communication.pre_execution",
        reason="deny: resolution.grounding.ungrounded_claim",
        decided_at=_NOW.isoformat(),
        correlation_id="corr-grounding",
        request_id="req-grounding",
        tenant_id=_TENANT,
        subject_kind="communication",
        metadata={"session_id": _SESSION_ID},
        evaluated_rules=(
            PolicyEvaluationResultRecord(
                policy_name="resolution.grounding",
                rule_id="ungrounded_claim",
                decision="deny",
                severity=30,
                reason="ungrounded_claim",
                evaluated_at=_NOW.isoformat(),
                metadata={
                    "structured_handoff": handoff,
                    "grounding_trace": trace,
                },
                policy_version="test",
            ),
        ),
    )


def _crisis_decision(
    *,
    decision_id: str = _CRISIS_DENY_ID,
    decision: str = "deny",
    policy_name: str = "crisis.block_sku",
    template: str = "block_sku",
) -> GovernanceDecisionRecord:
    return GovernanceDecisionRecord(
        decision_id=decision_id,
        decision=decision,
        stage="pre_execution",
        policy_chain_id="crisis.chain",
        reason=f"crisis:{template} test handoff",
        decided_at=_NOW.isoformat(),
        correlation_id="corr-crisis",
        request_id="req-crisis",
        tenant_id=_TENANT,
        subject_kind="execution",
        metadata={"session_id": _SESSION_ID},
        evaluated_rules=(
            PolicyEvaluationResultRecord(
                policy_name=policy_name,
                rule_id=f"crisis_{template}",
                decision=decision,
                severity=40,
                reason=f"crisis {template}",
                evaluated_at=_NOW.isoformat(),
                metadata={
                    "template": template,
                    "redis_key": f"crisis:{_TENANT}:{template}",
                },
                policy_version="test",
            ),
        ),
    )


async def _runtime() -> tuple[
    EscalationAgentRuntime,
    InMemoryEscalationPersistence,
    InMemoryGovernanceRepository,
    InMemorySessionPersistence,
]:
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
        governance,
        sessions,
    )


@pytest.mark.asyncio
async def test_escalation_agent_creates_pending_record_from_deny_only() -> None:
    runtime, escalations, governance, _sessions = await _runtime()

    record = await runtime.create_for_governance_denial(
        governance_decision_id=_DENY_ID,
        expected_tenant_id=_TENANT,
    )

    assert record.status == EscalationStatus.PENDING.value
    assert record.resolved_at is None
    assert record.resolution is None
    assert record.escalation_id == str(
        derive_escalation_id(
            tenant_id=_TENANT,
            session_id=_SESSION_ID,
            governance_decision_id=_DENY_ID,
        )
    )
    assert await escalations.get_escalation(
        record.escalation_id,
        expected_tenant_id=_TENANT,
    ) == record
    decisions = await governance.query_decisions(
        DecisionQuery(tenant_id=_TENANT)
    )
    assert [d.decision_id for d in decisions.items] == [_DENY_ID]


@pytest.mark.asyncio
async def test_escalation_pipeline_accepts_escalate_and_marks_high_priority() -> None:
    escalations = InMemoryEscalationPersistence()
    governance = InMemoryGovernanceRepository()
    sessions = InMemorySessionPersistence()
    await sessions.save_session(_session())
    await governance.record_decision(
        _decision(decision_id=_ESCALATE_ID, decision="escalate")
    )
    runtime = EscalationAgentRuntime(
        escalation_persistence=escalations,
        governance_repository=governance,
        session_persistence=sessions,
    )

    prepared = await runtime.prepare_governance_escalation_outbox(
        governance_decision_id=_ESCALATE_ID,
        expected_tenant_id=_TENANT,
    )
    second = await runtime.prepare_governance_escalation_outbox(
        governance_decision_id=_ESCALATE_ID,
        expected_tenant_id=_TENANT,
    )

    assert second.escalation == prepared.escalation
    assert second.outbox == prepared.outbox
    assert prepared.escalation.handoff_kind == EscalationHandoffKind.ESCALATION.value
    assert prepared.escalation.priority == EscalationPriority.HIGH.value
    assert prepared.escalation.metadata["source_decision"] == "escalate"
    assert prepared.outbox.metadata["source_decision"] == "escalate"
    assert prepared.outbox.metadata["priority"] == "high"


@pytest.mark.asyncio
async def test_crisis_decision_is_high_priority_and_sorted_above_routine_denial() -> None:
    escalations = InMemoryEscalationPersistence()
    governance = InMemoryGovernanceRepository()
    sessions = InMemorySessionPersistence()
    await sessions.save_session(_session())
    await governance.record_decision(_decision())
    await governance.record_decision(_crisis_decision())
    runtime = EscalationAgentRuntime(
        escalation_persistence=escalations,
        governance_repository=governance,
        session_persistence=sessions,
    )

    routine = await runtime.create_for_governance_denial(
        governance_decision_id=_DENY_ID,
        expected_tenant_id=_TENANT,
    )
    crisis = await runtime.create_for_governance_denial(
        governance_decision_id=_CRISIS_DENY_ID,
        expected_tenant_id=_TENANT,
    )
    page = await runtime.list_escalations(
        query=EscalationQuery(status=EscalationStatus.PENDING.value),
        expected_tenant_id=_TENANT,
    )

    assert crisis.handoff_kind == EscalationHandoffKind.CRISIS.value
    assert crisis.priority == EscalationPriority.HIGH.value
    assert crisis.metadata["crisis"] is True
    assert crisis.metadata["crisis_policy"] == "crisis.block_sku"
    assert [item.escalation_id for item in page.items] == [
        crisis.escalation_id,
        routine.escalation_id,
    ]


@pytest.mark.asyncio
async def test_ungrounded_denial_creates_handoff_metadata_and_timeline() -> None:
    escalations = InMemoryEscalationPersistence()
    governance = InMemoryGovernanceRepository()
    sessions = InMemorySessionPersistence()
    await sessions.save_session(_session())
    await governance.record_decision(_grounding_decision())
    runtime = EscalationAgentRuntime(
        escalation_persistence=escalations,
        governance_repository=governance,
        session_persistence=sessions,
    )

    record = await runtime.create_for_governance_denial(
        governance_decision_id=_DENY_ID,
        expected_tenant_id=_TENANT,
    )

    assert record.metadata["structured_handoff"]["escalation"] == (
        "ungrounded_claim"
    )
    assert record.metadata["grounding_trace"]["status"] == "ungrounded"
    page = await sessions.list_events(
        SessionEventQuery(session_id=SessionId(uuid.UUID(_SESSION_ID))),
        expected_tenant_id=_TENANT,
    )
    handoff_events = [
        event
        for event in page.events
        if event.kind is SessionEventKind.OPERATIONAL_OBSERVATION
        and event.payload.get("event_type")
        == "grounding_escalation_handoff_created"
    ]
    assert len(handoff_events) == 1
    assert handoff_events[0].payload["escalation_id"] == record.escalation_id
    assert handoff_events[0].payload["grounding_trace"]["status"] == (
        "ungrounded"
    )


@pytest.mark.asyncio
async def test_escalation_agent_is_idempotent_by_governance_decision() -> None:
    runtime, _escalations, _governance, _sessions = await _runtime()

    first = await runtime.create_for_governance_denial(
        governance_decision_id=_DENY_ID,
        expected_tenant_id=_TENANT,
    )
    second = await runtime.create_for_governance_denial(
        governance_decision_id=_DENY_ID,
        expected_tenant_id=_TENANT,
    )

    assert second == first


@pytest.mark.asyncio
async def test_escalation_agent_rejects_non_deny_and_cross_tenant() -> None:
    escalations = InMemoryEscalationPersistence()
    governance = InMemoryGovernanceRepository()
    sessions = InMemorySessionPersistence()
    await sessions.save_session(_session())
    await governance.record_decision(
        _decision(decision_id=_ALLOW_ID, decision="allow")
    )
    runtime = EscalationAgentRuntime(
        escalation_persistence=escalations,
        governance_repository=governance,
        session_persistence=sessions,
    )

    with pytest.raises(EscalationRuntimeError, match="DENY"):
        await runtime.create_for_governance_denial(
            governance_decision_id=_ALLOW_ID,
            expected_tenant_id=_TENANT,
        )
    with pytest.raises(EscalationRuntimeError, match="unknown"):
        await runtime.create_for_governance_denial(
            governance_decision_id=_ALLOW_ID,
            expected_tenant_id=_OTHER_TENANT,
        )


@pytest.mark.asyncio
async def test_deny_override_refuses_escalate_and_crisis_handoffs() -> None:
    escalations = InMemoryEscalationPersistence()
    governance = InMemoryGovernanceRepository()
    sessions = InMemorySessionPersistence()
    await sessions.save_session(_session())
    await governance.record_decision(
        _decision(decision_id=_ESCALATE_ID, decision="escalate")
    )
    await governance.record_decision(_crisis_decision())
    runtime = EscalationAgentRuntime(
        escalation_persistence=escalations,
        governance_repository=governance,
        session_persistence=sessions,
    )

    escalated = await runtime.create_for_governance_escalation(
        governance_decision_id=_ESCALATE_ID,
        expected_tenant_id=_TENANT,
    )
    crisis = await runtime.create_for_governance_denial(
        governance_decision_id=_CRISIS_DENY_ID,
        expected_tenant_id=_TENANT,
    )

    with pytest.raises(EscalationRuntimeError, match="DENY"):
        await runtime.approve_escalation(
            escalation_id=escalated.escalation_id,
            expected_tenant_id=_TENANT,
            resolution="incorrectly override escalate",
            resolved_by="principal-manager",
        )
    with pytest.raises(EscalationRuntimeError, match="crisis"):
        await runtime.reject_escalation(
            escalation_id=crisis.escalation_id,
            expected_tenant_id=_TENANT,
            resolution="incorrectly reject crisis",
            resolved_by="principal-manager",
        )


@pytest.mark.asyncio
async def test_manager_approval_creates_governance_override_provenance() -> None:
    runtime, _escalations, governance, _sessions = await _runtime()
    record = await runtime.create_for_governance_denial(
        governance_decision_id=_DENY_ID,
        expected_tenant_id=_TENANT,
    )

    approved = await runtime.approve_escalation(
        escalation_id=record.escalation_id,
        expected_tenant_id=_TENANT,
        resolution="manager approves one-time override",
        resolved_by="principal-manager",
    )

    override_id = str(
        derive_escalation_override_decision_id(
            escalation_id=record.escalation_id,
            governance_decision_id=_DENY_ID,
            tenant_id=_TENANT,
        )
    )
    assert approved.status == EscalationStatus.APPROVED.value
    assert approved.metadata["governance_override_decision_id"] == override_id
    override = await governance.get_decision(
        override_id,
        expected_tenant_id=_TENANT,
    )
    assert override is not None
    assert override.decision == "allow"
    assert override.metadata["override_authority"] == "human_manager"
    assert override.metadata["source_governance_decision_id"] == _DENY_ID
    original = await governance.get_decision(
        _DENY_ID,
        expected_tenant_id=_TENANT,
    )
    assert original is not None
    assert original.decision == "deny"
    actions = await governance.get_enforcement_actions(
        override_id,
        expected_tenant_id=_TENANT,
    )
    assert len(actions) == 1
    assert actions[0].handler_name == "human_manager_override"


@pytest.mark.asyncio
async def test_manager_rejection_closes_without_override() -> None:
    runtime, _escalations, governance, _sessions = await _runtime()
    record = await runtime.create_for_governance_denial(
        governance_decision_id=_DENY_ID,
        expected_tenant_id=_TENANT,
    )

    rejected = await runtime.reject_escalation(
        escalation_id=record.escalation_id,
        expected_tenant_id=_TENANT,
        resolution="manager keeps denial in force",
        resolved_by="principal-manager",
    )

    override_id = str(
        derive_escalation_override_decision_id(
            escalation_id=record.escalation_id,
            governance_decision_id=_DENY_ID,
            tenant_id=_TENANT,
        )
    )
    assert rejected.status == EscalationStatus.REJECTED.value
    assert rejected.metadata["denial_lineage_intact"] is True
    assert await governance.get_decision(
        override_id,
        expected_tenant_id=_TENANT,
    ) is None
    original = await governance.get_decision(
        _DENY_ID,
        expected_tenant_id=_TENANT,
    )
    assert original is not None
    assert original.decision == "deny"


def test_escalation_worker_task_accepts_only_primitive_lineage() -> None:
    from app.workers.escalation_tasks import (
        create_governance_escalation_runtime,
    )

    signature = inspect.signature(create_governance_escalation_runtime)
    assert tuple(signature.parameters) == (
        "governance_decision_id",
        "tenant_id",
        "session_id",
    )


def test_dispatch_service_keeps_celery_as_transport_only() -> None:
    text = Path("apps/backend/app/services/dispatch_service.py").read_text(
        encoding="utf-8"
    )
    assert ".delay(" not in text
    assert "celery" not in text.lower()
