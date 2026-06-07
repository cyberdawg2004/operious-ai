"""Crisis governance decisions route to durable escalation handoffs."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.agents.tools import invoker
from app.governance.decisions import GovernanceDecision, PolicyEvaluationResult
from app.governance.enums import Decision, EnforcementStage, ViolationSeverity

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
        metadata={"session_id": _SESSION_ID},
    )
