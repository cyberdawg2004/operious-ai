"""Crisis governance decisions route to durable escalation handoffs."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import cast

import pytest

from app.agents.tools import invoker
from app.cognition.exceptions import CognitionGovernanceRejectionError
from app.governance.decisions import GovernanceDecision, PolicyEvaluationResult
from app.governance.enums import Decision, EnforcementStage, ViolationSeverity
from app.governance.persistence import (
    InMemoryGovernanceRepository,
    PostgresGovernanceRepository,
)
from app.governance.persistence.serializers import decision_to_record, trace_to_record
from app.governance.tracing import GovernanceTrace
from app.workers import agent_tasks

_TENANT = "tenant-crisis-handoff"
_SESSION_ID = "00000000-0000-0000-0000-00000000c101"
_DECISION_ID = uuid.UUID("00000000-0000-0000-0000-00000000c102")
_NOW = datetime(2026, 6, 7, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_crisis_escalate_all_publishes_governance_escalation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher = _RecordingPublisher()
    monkeypatch.setattr(invoker, "CeleryEscalationPublisher", lambda: publisher)

    published = await invoker._publish_crisis_handoff_if_needed(  # pyright: ignore[reportPrivateUsage]
        decision=_decision(
            decision=Decision.ESCALATE,
            policy_name="crisis.escalate_all",
            template="escalate_all",
        ),
        tenant_id=_TENANT,
        session_id=_SESSION_ID,
    )

    assert published is True
    assert publisher.escalations == [
        (str(_DECISION_ID), _TENANT, _SESSION_ID)
    ]
    assert publisher.denials == []


@pytest.mark.asyncio
async def test_crisis_deny_publishes_existing_denial_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher = _RecordingPublisher()
    monkeypatch.setattr(invoker, "CeleryEscalationPublisher", lambda: publisher)

    published = await invoker._publish_crisis_handoff_if_needed(  # pyright: ignore[reportPrivateUsage]
        decision=_decision(
            decision=Decision.DENY,
            policy_name="crisis.block_sku",
            template="block_sku",
        ),
        tenant_id=_TENANT,
        session_id=_SESSION_ID,
    )

    assert published is True
    assert publisher.denials == [(str(_DECISION_ID), _TENANT, _SESSION_ID)]
    assert publisher.escalations == []


@pytest.mark.asyncio
async def test_crisis_require_approval_does_not_duplicate_action_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher = _RecordingPublisher()
    monkeypatch.setattr(invoker, "CeleryEscalationPublisher", lambda: publisher)

    published = await invoker._publish_crisis_handoff_if_needed(  # pyright: ignore[reportPrivateUsage]
        decision=_decision(
            decision=Decision.REQUIRE_APPROVAL,
            policy_name="crisis.halt_refunds",
            template="halt_refunds",
        ),
        tenant_id=_TENANT,
        session_id=_SESSION_ID,
    )

    assert published is False
    assert publisher.denials == []
    assert publisher.escalations == []


@pytest.mark.asyncio
async def test_diagnostic_terminal_handoff_restores_attached_crisis_source_decision() -> None:
    repo = InMemoryGovernanceRepository()
    decision = _decision(
        decision=Decision.ESCALATE,
        policy_name="crisis.escalate_all",
        template="escalate_all",
    )
    error = CognitionGovernanceRejectionError(
        "governance rejected diagnostic model output"
    )
    setattr(error, "governance_decision_id", str(decision.decision_id))
    setattr(error, "governance_decision_record", decision_to_record(decision))
    setattr(error, "governance_trace_record", trace_to_record(_trace(decision)))

    handoff = await agent_tasks._ensure_diagnostic_block_governance_handoff(  # pyright: ignore[reportPrivateUsage]
        governance_repo=cast(PostgresGovernanceRepository, repo),
        work_item=agent_tasks._DiagnosticExecutionWorkItem(  # pyright: ignore[reportPrivateUsage]
            execution_id="00000000-0000-0000-0000-00000000c103",
            attempt_id="00000000-0000-0000-0000-00000000c104",
            attempt_number=1,
            dispatch_id="00000000-0000-0000-0000-00000000c105",
            session_id=_SESSION_ID,
            tenant_id=_TENANT,
            content="Customer asks for charger troubleshooting during crisis mode.",
        ),
        failure={"error_class": "GOVERNANCE_DENY"},
        exc=error,
    )

    assert handoff.decision_id == str(_DECISION_ID)
    assert handoff.source_decision is Decision.ESCALATE
    stored_decision = await repo.get_decision(
        str(_DECISION_ID),
        expected_tenant_id=_TENANT,
    )
    stored_trace = await repo.get_trace(
        str(_DECISION_ID),
        expected_tenant_id=_TENANT,
    )
    assert stored_decision is not None
    assert stored_decision.decision == Decision.ESCALATE.value
    assert stored_decision.evaluated_rules[0].policy_name == "crisis.escalate_all"
    assert stored_trace is not None
    assert stored_trace.final_decision == Decision.ESCALATE.value


class _RecordingPublisher:
    def __init__(self) -> None:
        self.denials: list[tuple[str, str, str | None]] = []
        self.escalations: list[tuple[str, str, str | None]] = []

    async def publish_governance_denial(
        self,
        *,
        governance_decision_id: str,
        tenant_id: str,
        session_id: str | None = None,
    ) -> None:
        self.denials.append((governance_decision_id, tenant_id, session_id))

    async def publish_governance_escalation(
        self,
        *,
        governance_decision_id: str,
        tenant_id: str,
        session_id: str | None = None,
    ) -> None:
        self.escalations.append(
            (governance_decision_id, tenant_id, session_id)
        )


def _decision(
    *,
    decision: Decision,
    policy_name: str,
    template: str,
) -> GovernanceDecision:
    result = PolicyEvaluationResult(
        policy_name=policy_name,
        rule_id=f"crisis_{template}",
        decision=decision,
        severity=ViolationSeverity.CRITICAL,
        reason=f"crisis {template}",
        evaluated_at=_NOW,
        metadata={"template": template},
    )
    return GovernanceDecision(
        decision_id=_DECISION_ID,
        decision=decision,
        stage=EnforcementStage.PRE_EXECUTION,
        policy_chain_id="crisis.test",
        evaluated_rules=(result,),
        violations=(),
        restrictions=(),
        reason=f"{decision.value}: crisis {template}",
        decided_at=_NOW,
        metadata={
            "session_id": _SESSION_ID,
            "tenant_id": _TENANT,
            "subject_kind": "diagnostic_execution",
        },
    )


def _trace(decision: GovernanceDecision) -> GovernanceTrace:
    return GovernanceTrace(
        decision_id=decision.decision_id,
        request_id=None,
        stage=EnforcementStage.PRE_EXECUTION,
        action="ai.diagnostic_classification",
        resource="execution:00000000-0000-0000-0000-00000000c103",
        actor="agent:diagnostic",
        tenant_id=_TENANT,
        started_at=_NOW,
        ended_at=_NOW,
        latency_ms=1.0,
        status="ok",
        final_decision=decision.decision,
        policy_chain_id=decision.policy_chain_id,
        policy_traces=(),
        rule_count=len(decision.evaluated_rules),
        violation_count=len(decision.violations),
        restriction_count=len(decision.restrictions),
        subject_kind="diagnostic_execution",
        enforcement_handler="escalate",
        enforcement_status="ok",
        enforcement_latency_ms=1.0,
        metadata={
            "session_id": _SESSION_ID,
            "tenant_id": _TENANT,
            "subject_kind": "diagnostic_execution",
        },
    )
