"""Human-review resolution denial handoff tests."""

from __future__ import annotations

import inspect
import uuid
from datetime import datetime
from typing import Any, cast

import pytest

from app.escalation import (
    EscalationAgentRuntime,
    EscalationHandoffKind,
    EscalationOutboxStatus,
    EscalationPriority,
    EscalationStatus,
    InMemoryEscalationPersistence,
)
from app.governance.enums import Decision
from app.governance.persistence import (
    GovernanceDecisionRecord,
    InMemoryGovernanceRepository,
    PolicyEvaluationResultRecord,
    PostgresGovernanceRepository,
)
from app.resolution.enums import (
    ResolutionAutonomyDecision,
    ResolutionGovernanceVerdict,
    ResolutionOutboundDraftStatus,
    ResolutionProposalStatus,
    ResolutionSupervisorVerdict,
)
from app.resolution.identity import (
    ResolutionOutboundDraftId,
    ResolutionProposalId,
)
from app.resolution.persistence import (
    ResolutionOutboundDraftRecord,
    ResolutionProposalRecord,
)
from app.session.enums import SessionLifecyclePhase, SessionScope
from app.session.identity import SessionId, SessionLineageId
from app.session.persistence import (
    InMemorySessionPersistence,
    SessionRecord,
)
from app.workers import agent_tasks

_TENANT_ID = "tenant-resolution-safety"
_SESSION_ID = "11111111-1111-4111-8111-111111111111"
_EXECUTION_ID = "22222222-2222-4222-8222-222222222222"
_ATTEMPT_ID = "33333333-3333-4333-8333-333333333333"
_DISPATCH_ID = "44444444-4444-4444-8444-444444444444"
_DENY_ID = "55555555-5555-4555-8555-555555555555"
_PROPOSAL_ID = "66666666-6666-4666-8666-666666666666"
_DRAFT_ID = "77777777-7777-4777-8777-777777777777"
_NOW = "2026-06-06T22:36:03+00:00"
_NOW_DT = datetime.fromisoformat(_NOW)


def test_resolution_denial_detection_escalates_human_review_categories() -> None:
    assert agent_tasks._resolution_denial_should_escalate(
        _resolution_decision(flags=("safety_risk",))
    )
    # Fix 3 policy change: this used to assert NOT escalate. Legal/chargeback
    # severe-resolution DENYs now create a human handoff like safety.
    assert agent_tasks._resolution_denial_should_escalate(
        _resolution_decision(flags=("legal_or_chargeback_risk",))
    )
    assert agent_tasks._resolution_denial_should_escalate(
        _resolution_decision(flags=("fraud_risk",))
    )
    assert not agent_tasks._resolution_denial_should_escalate(
        _resolution_decision(rule_id="ungrounded_claim", flags=("safety_risk",))
    )
    assert not agent_tasks._resolution_denial_should_escalate(
        _resolution_decision(rule_id="evidence_required")
    )
    assert not agent_tasks._resolution_denial_should_escalate(
        _resolution_decision(
            policy_chain_id="cognition.diagnostic.terminal_block",
            flags=("safety_risk",),
        )
    )
    assert not agent_tasks._resolution_denial_should_escalate(
        _resolution_decision(decision="allow", flags=("safety_risk",))
    )


@pytest.mark.asyncio
async def test_resolution_human_review_denial_publishes_governance_denial_escalation_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class _Publisher:
        async def publish_governance_denial(
            self,
            *,
            governance_decision_id: str,
            tenant_id: str,
            session_id: str | None = None,
        ) -> None:
            calls.append(
                {
                    "governance_decision_id": governance_decision_id,
                    "tenant_id": tenant_id,
                    "session_id": session_id,
                }
            )

    monkeypatch.setattr(agent_tasks, "CeleryEscalationPublisher", _Publisher)
    published = await agent_tasks._publish_resolution_safety_escalation_if_present(
        work_item=_work_item(),
        resolution_append=agent_tasks._ResolutionAppendResult(
            success=True,
            safety_escalation_governance_decision_id=_DENY_ID,
        ),
    )

    assert published is True
    assert calls == [
        {
            "governance_decision_id": _DENY_ID,
            "tenant_id": _TENANT_ID,
            "session_id": _SESSION_ID,
        }
    ]


@pytest.mark.asyncio
async def test_resolution_human_review_escalation_publish_noops_without_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class _Publisher:
        async def publish_governance_denial(self, **kwargs: Any) -> None:
            calls.append(dict(kwargs))

    monkeypatch.setattr(agent_tasks, "CeleryEscalationPublisher", _Publisher)
    published = await agent_tasks._publish_resolution_safety_escalation_if_present(
        work_item=_work_item(),
        resolution_append=agent_tasks._ResolutionAppendResult(success=True),
    )

    assert published is False
    assert calls == []


def test_resolution_human_review_handoff_uses_escalation_pipeline_not_crisis() -> None:
    source = inspect.getsource(
        agent_tasks._publish_resolution_safety_escalation_if_present
    )

    assert "publish_governance_denial" in source
    assert "publish_crisis" not in source


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "flag",
    ("legal_or_chargeback_risk", "fraud_risk"),
)
async def test_resolution_human_review_denial_prepares_handoff_and_outbox(
    flag: str,
) -> None:
    decision = _resolution_decision(flags=(flag,))
    escalations = InMemoryEscalationPersistence()
    governance = InMemoryGovernanceRepository()
    sessions = InMemorySessionPersistence()
    await sessions.save_session(_session())
    await governance.record_decision(decision)

    selected = await agent_tasks._resolution_safety_escalation_governance_decision_id(
        governance_repo=cast(PostgresGovernanceRepository, governance),
        work_item=_work_item(),
        proposal=_proposal(),
        draft=_draft(),
    )
    runtime = EscalationAgentRuntime(
        escalation_persistence=escalations,
        governance_repository=governance,
        session_persistence=sessions,
    )

    assert selected == _DENY_ID
    prepared = await runtime.prepare_governance_denial_outbox(
        governance_decision_id=selected,
        expected_tenant_id=_TENANT_ID,
        session_id=_SESSION_ID,
    )
    second = await runtime.prepare_governance_denial_outbox(
        governance_decision_id=selected,
        expected_tenant_id=_TENANT_ID,
        session_id=_SESSION_ID,
    )

    assert second.escalation == prepared.escalation
    assert second.outbox == prepared.outbox
    assert prepared.escalation.status == EscalationStatus.PENDING.value
    assert prepared.escalation.session_id == _SESSION_ID
    assert prepared.escalation.tenant_id == _TENANT_ID
    assert prepared.escalation.governance_decision_id == _DENY_ID
    assert prepared.escalation.reason == decision.reason
    assert prepared.escalation.handoff_kind == EscalationHandoffKind.DENIAL.value
    assert prepared.escalation.priority == EscalationPriority.NORMAL.value
    assert prepared.escalation.metadata["source_decision"] == Decision.DENY.value
    assert prepared.escalation.metadata["source_policy_chain_id"] == (
        "resolution.communication.pre_execution"
    )
    assert prepared.outbox.status is EscalationOutboxStatus.PENDING
    assert prepared.outbox.escalation_id == prepared.escalation.escalation_id
    assert prepared.outbox.metadata["governance_decision_id"] == _DENY_ID
    assert prepared.outbox.metadata["session_id"] == _SESSION_ID
    assert prepared.outbox.metadata["handoff_kind"] == EscalationHandoffKind.DENIAL.value
    assert prepared.outbox.metadata["priority"] == EscalationPriority.NORMAL.value


@pytest.mark.asyncio
async def test_resolution_routine_denial_is_not_selected_for_handoff() -> None:
    governance = InMemoryGovernanceRepository()
    await governance.record_decision(_resolution_decision(rule_id="evidence_required"))

    selected = await agent_tasks._resolution_safety_escalation_governance_decision_id(
        governance_repo=cast(PostgresGovernanceRepository, governance),
        work_item=_work_item(),
        proposal=_proposal(),
        draft=_draft(),
    )

    assert selected is None


def _work_item() -> agent_tasks._DiagnosticExecutionWorkItem:
    return agent_tasks._DiagnosticExecutionWorkItem(
        execution_id=_EXECUTION_ID,
        attempt_id=_ATTEMPT_ID,
        attempt_number=1,
        dispatch_id=_DISPATCH_ID,
        session_id=_SESSION_ID,
        tenant_id=_TENANT_ID,
        content="The PowerCore emitted smoke and a burning smell.",
    )


def _session() -> SessionRecord:
    sid = SessionId(uuid.UUID(_SESSION_ID))
    return SessionRecord(
        session_id=sid,
        scope=SessionScope.TENANT,
        external_handle="ticket-resolution-human-review",
        tenant_id=_TENANT_ID,
        principal_id="principal-agent",
        opened_at=_NOW_DT,
        lifecycle_phase=SessionLifecyclePhase.ACTIVE,
        lifecycle_recorded_at=_NOW_DT,
        lifecycle_reason=None,
        lineage_id=SessionLineageId(uuid.UUID(_SESSION_ID)),
        root_session_id=sid,
        parent_session_id=None,
        ancestor_session_ids=(),
        lineage_depth=0,
        sequence_head=-1,
        revision=1,
    )


def _proposal(
    *,
    status: ResolutionProposalStatus = ResolutionProposalStatus.DENIED,
    governance_decision_id: str | None = _DENY_ID,
) -> ResolutionProposalRecord:
    return ResolutionProposalRecord(
        proposal_id=ResolutionProposalId(uuid.UUID(_PROPOSAL_ID)),
        tenant_id=_TENANT_ID,
        session_id=_SESSION_ID,
        execution_id=_EXECUTION_ID,
        dispatch_id=_DISPATCH_ID,
        diagnostic_event_id=None,
        proposed_customer_reply="Human review required before responding.",
        resolution_category="human_review_required",
        confidence=0.2,
        supervisor_verdict=ResolutionSupervisorVerdict.NEEDS_HUMAN_REVIEW,
        governance_verdict=ResolutionGovernanceVerdict.DENY,
        autonomy_decision=ResolutionAutonomyDecision.DENIED,
        status=status,
        created_at=_NOW_DT,
        updated_at=_NOW_DT,
        governance_decision_id=(
            uuid.UUID(governance_decision_id)
            if governance_decision_id is not None
            else None
        ),
    )


def _draft() -> ResolutionOutboundDraftRecord:
    return ResolutionOutboundDraftRecord(
        draft_id=ResolutionOutboundDraftId(uuid.UUID(_DRAFT_ID)),
        tenant_id=_TENANT_ID,
        proposal_id=ResolutionProposalId(uuid.UUID(_PROPOSAL_ID)),
        session_id=_SESSION_ID,
        execution_id=_EXECUTION_ID,
        dispatch_id=_DISPATCH_ID,
        diagnostic_event_id=None,
        governance_decision_id=uuid.UUID(_DENY_ID),
        status=ResolutionOutboundDraftStatus.DENIED,
        draft_body="Human review required before responding.",
        draft_body_sha256="fixture",
        resolution_category="human_review_required",
        confidence=0.2,
        created_at=_NOW_DT,
        updated_at=_NOW_DT,
    )


def _resolution_decision(
    *,
    decision: str = "deny",
    policy_chain_id: str = "resolution.communication.pre_execution",
    rule_id: str = "severe_resolution_risk",
    flags: tuple[str, ...] = (),
) -> GovernanceDecisionRecord:
    return GovernanceDecisionRecord(
        decision_id=_DENY_ID,
        decision=decision,
        stage="pre_execution",
        policy_chain_id=policy_chain_id,
        reason=f"{decision}: resolution.communication.{rule_id}",
        decided_at=_NOW,
        correlation_id=_DISPATCH_ID,
        request_id="resolution:proposal",
        tenant_id=_TENANT_ID,
        subject_kind="communication",
        evaluated_rules=(
            PolicyEvaluationResultRecord(
                policy_name="resolution.communication",
                rule_id=rule_id,
                decision=decision,
                severity=40,
                reason=f"resolution communication denied: {rule_id}",
                evaluated_at=_NOW,
                metadata={"flags": list(flags)},
            ),
        ),
        metadata={
            "session_id": _SESSION_ID,
            "execution_id": _EXECUTION_ID,
            "dispatch_id": _DISPATCH_ID,
        },
    )
