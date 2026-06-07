"""Safety-denied resolution handoff tests."""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from app.governance.persistence import (
    GovernanceDecisionRecord,
    PolicyEvaluationResultRecord,
)
from app.workers import agent_tasks

_TENANT_ID = "tenant-resolution-safety"
_SESSION_ID = "11111111-1111-4111-8111-111111111111"
_EXECUTION_ID = "22222222-2222-4222-8222-222222222222"
_ATTEMPT_ID = "33333333-3333-4333-8333-333333333333"
_DISPATCH_ID = "44444444-4444-4444-8444-444444444444"
_DENY_ID = "55555555-5555-4555-8555-555555555555"
_NOW = "2026-06-06T22:36:03+00:00"


def test_resolution_safety_denial_detection_is_scoped_to_safety() -> None:
    assert agent_tasks._resolution_denial_should_escalate(
        _resolution_decision(flags=("safety_risk",))
    )
    assert not agent_tasks._resolution_denial_should_escalate(
        _resolution_decision(flags=("legal_or_chargeback_risk",))
    )
    assert not agent_tasks._resolution_denial_should_escalate(
        _resolution_decision(rule_id="ungrounded_claim", flags=("safety_risk",))
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
async def test_resolution_safety_denial_publishes_governance_denial_escalation_intent(
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
async def test_resolution_safety_escalation_publish_noops_without_safety_denial(
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


def test_resolution_safety_handoff_uses_escalation_pipeline_not_crisis() -> None:
    source = inspect.getsource(
        agent_tasks._publish_resolution_safety_escalation_if_present
    )

    assert "publish_governance_denial" in source
    assert "publish_crisis" not in source


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
