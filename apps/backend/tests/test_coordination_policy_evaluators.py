"""Built-in coordination-policy evaluators — correctness + determinism.

Three evaluators exercised:

* `TopologyEvaluator`         — sender/recipient/direction/type rules.
* `EscalationEvaluator`       — escalation-scope rules.
* `TenantIsolationEvaluator`  — cross-tenant boundary policing.

Each test stays scoped to ONE evaluator and asserts behaviour on
input fields the runtime composes from a dispatch request.
"""

from __future__ import annotations

import pytest

from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
    CoordinationPriority,
)
from app.coordination.identity import (
    derive_coordination_id,
    derive_message_id,
)
from app.coordination.policy.contracts.requests import (
    CoordinationPolicyEvaluationRequest,
)
from app.coordination.policy.enums import (
    CoordinationEscalationType,
    CoordinationPolicyDecision,
    CoordinationPolicyScope,
    CoordinationRestrictionType,
)
from app.coordination.policy.evaluators.builtin import (
    EscalationEvaluator,
    TenantIsolationEvaluator,
    TopologyEvaluator,
)
from app.coordination.policy.identity import derive_policy_id
from app.coordination.policy.models.escalation import (
    CoordinationPolicyEscalation,
)
from app.coordination.policy.models.policy import CoordinationPolicy
from app.coordination.policy.models.restriction import (
    CoordinationPolicyRestriction,
)
from app.coordination.policy.models.rule import CoordinationPolicyRule


def _request(
    *,
    sender: str = "agent:retriever",
    recipient: str = "agent:planner",
    direction: CoordinationDirection = CoordinationDirection.AGENT_TO_AGENT,
    message_type: CoordinationMessageType = CoordinationMessageType.HANDOFF,
    tenant_id: str | None = "tenant:t1",
    sender_tenant_id: str | None = "tenant:t1",
    recipient_tenant_id: str | None = "tenant:t1",
) -> CoordinationPolicyEvaluationRequest:
    return CoordinationPolicyEvaluationRequest(
        sender_id=sender,
        recipient_id=recipient,
        direction=direction,
        message_type=message_type,
        coordination_id=derive_coordination_id(seed=f"c:{sender}:{recipient}"),
        coordination_message_id=derive_message_id(
            seed=f"m:{sender}:{recipient}"
        ),
        priority=CoordinationPriority.NORMAL,
        tenant_id=tenant_id,
        sender_tenant_id=sender_tenant_id,
        recipient_tenant_id=recipient_tenant_id,
    )


# ─── TopologyEvaluator ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_topology_evaluator_no_policies_emits_no_findings() -> None:
    ev = TopologyEvaluator()
    findings = await ev.evaluate(_request())
    assert findings == ()


@pytest.mark.asyncio
async def test_topology_evaluator_emits_deny_finding_for_matching_rule() -> None:
    policy = CoordinationPolicy(
        policy_id=derive_policy_id(seed="topology.deny"),
        name="topology.deny",
        scope=CoordinationPolicyScope.TOPOLOGY,
        rules=(
            CoordinationPolicyRule(
                rule_id="forbid_retriever_to_planner",
                scope=CoordinationPolicyScope.TOPOLOGY,
                decision=CoordinationPolicyDecision.DENY,
                sender_pattern="agent:retriever",
                recipient_pattern="agent:planner",
            ),
        ),
    )
    ev = TopologyEvaluator(policies=(policy,))
    findings = await ev.evaluate(_request())
    assert len(findings) == 1
    assert findings[0].decision is CoordinationPolicyDecision.DENY
    assert findings[0].rule_id == "forbid_retriever_to_planner"


@pytest.mark.asyncio
async def test_topology_evaluator_skips_non_matching_rules() -> None:
    policy = CoordinationPolicy(
        policy_id=derive_policy_id(seed="topology.alt"),
        name="topology.alt",
        scope=CoordinationPolicyScope.TOPOLOGY,
        rules=(
            CoordinationPolicyRule(
                rule_id="never-matches",
                scope=CoordinationPolicyScope.TOPOLOGY,
                decision=CoordinationPolicyDecision.DENY,
                sender_pattern="agent:someone-else",
                recipient_pattern="agent:another",
            ),
        ),
    )
    ev = TopologyEvaluator(policies=(policy,))
    findings = await ev.evaluate(_request())
    assert findings == ()


@pytest.mark.asyncio
async def test_topology_evaluator_direction_filter() -> None:
    policy = CoordinationPolicy(
        policy_id=derive_policy_id(seed="topology.dir"),
        name="topology.dir",
        scope=CoordinationPolicyScope.TOPOLOGY,
        rules=(
            CoordinationPolicyRule(
                rule_id="only_supervisor_to_agent",
                scope=CoordinationPolicyScope.DIRECTION,
                decision=CoordinationPolicyDecision.DENY,
                direction=CoordinationDirection.SUPERVISOR_TO_AGENT,
            ),
        ),
    )
    ev = TopologyEvaluator(policies=(policy,))
    findings = await ev.evaluate(
        _request(direction=CoordinationDirection.AGENT_TO_AGENT)
    )
    assert findings == ()
    findings = await ev.evaluate(
        _request(direction=CoordinationDirection.SUPERVISOR_TO_AGENT)
    )
    assert len(findings) == 1


@pytest.mark.asyncio
async def test_topology_evaluator_emits_restrict_with_attached_restrictions() -> None:
    restriction = CoordinationPolicyRestriction(
        kind=CoordinationRestrictionType.PRIORITY_CAP,
        target="agent:planner",
        value={"cap": 20},
        reason="cap planner priority",
    )
    policy = CoordinationPolicy(
        policy_id=derive_policy_id(seed="topology.cap"),
        name="topology.cap",
        scope=CoordinationPolicyScope.TOPOLOGY,
        rules=(
            CoordinationPolicyRule(
                rule_id="cap_priority",
                scope=CoordinationPolicyScope.TOPOLOGY,
                decision=CoordinationPolicyDecision.RESTRICT,
                sender_pattern="agent:*",
                recipient_pattern="agent:planner",
                restrictions=(restriction,),
            ),
        ),
    )
    ev = TopologyEvaluator(policies=(policy,))
    findings = await ev.evaluate(_request())
    assert len(findings) == 1
    assert findings[0].decision is CoordinationPolicyDecision.RESTRICT
    assert findings[0].restrictions == (restriction,)


@pytest.mark.asyncio
async def test_topology_evaluator_is_deterministic_across_repeats() -> None:
    policy = CoordinationPolicy(
        policy_id=derive_policy_id(seed="topology.det"),
        name="topology.det",
        scope=CoordinationPolicyScope.TOPOLOGY,
        rules=(
            CoordinationPolicyRule(
                rule_id="r1",
                scope=CoordinationPolicyScope.TOPOLOGY,
                decision=CoordinationPolicyDecision.ALLOW,
                sender_pattern="agent:*",
                recipient_pattern="agent:*",
            ),
        ),
    )
    ev = TopologyEvaluator(policies=(policy,))
    a = await ev.evaluate(_request())
    b = await ev.evaluate(_request())
    # Finding ids derived from the same coordination_id seed are equal.
    assert tuple(f.finding_id for f in a) == tuple(f.finding_id for f in b)


# ─── EscalationEvaluator ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_escalation_evaluator_emits_finding_for_escalate_rule() -> None:
    escalation = CoordinationPolicyEscalation(
        kind=CoordinationEscalationType.HUMAN_REVIEW,
        target="approver:platform",
        reason="sensitive handoff",
    )
    policy = CoordinationPolicy(
        policy_id=derive_policy_id(seed="esc.sensitive"),
        name="esc.sensitive",
        scope=CoordinationPolicyScope.ESCALATION,
        rules=(
            CoordinationPolicyRule(
                rule_id="sensitive",
                scope=CoordinationPolicyScope.ESCALATION,
                decision=CoordinationPolicyDecision.ESCALATE,
                sender_pattern="agent:retriever",
                recipient_pattern="agent:planner",
                escalations=(escalation,),
            ),
        ),
    )
    ev = EscalationEvaluator(policies=(policy,))
    findings = await ev.evaluate(_request())
    assert len(findings) == 1
    assert findings[0].decision is CoordinationPolicyDecision.ESCALATE
    assert findings[0].escalations == (escalation,)


@pytest.mark.asyncio
async def test_escalation_evaluator_ignores_non_escalation_rules() -> None:
    policy = CoordinationPolicy(
        policy_id=derive_policy_id(seed="esc.noop"),
        name="esc.noop",
        scope=CoordinationPolicyScope.TOPOLOGY,
        rules=(
            CoordinationPolicyRule(
                rule_id="allow",
                scope=CoordinationPolicyScope.TOPOLOGY,
                decision=CoordinationPolicyDecision.ALLOW,
                sender_pattern="agent:*",
                recipient_pattern="agent:*",
            ),
        ),
    )
    ev = EscalationEvaluator(policies=(policy,))
    findings = await ev.evaluate(_request())
    assert findings == ()


# ─── TenantIsolationEvaluator ────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_isolation_deny_on_missing_tenant() -> None:
    ev = TenantIsolationEvaluator(require_tenant=True)
    findings = await ev.evaluate(_request(tenant_id=None))
    assert len(findings) == 1
    assert findings[0].decision is CoordinationPolicyDecision.DENY


@pytest.mark.asyncio
async def test_tenant_isolation_allow_when_same_tenant() -> None:
    ev = TenantIsolationEvaluator()
    findings = await ev.evaluate(
        _request(
            sender_tenant_id="tenant:t1", recipient_tenant_id="tenant:t1"
        )
    )
    assert findings == ()


@pytest.mark.asyncio
async def test_tenant_isolation_deny_on_disallowed_cross_tenant() -> None:
    ev = TenantIsolationEvaluator()
    findings = await ev.evaluate(
        _request(
            sender_tenant_id="tenant:a", recipient_tenant_id="tenant:b"
        )
    )
    assert len(findings) == 1
    assert findings[0].decision is CoordinationPolicyDecision.DENY


@pytest.mark.asyncio
async def test_tenant_isolation_annotates_on_allowed_cross_tenant() -> None:
    ev = TenantIsolationEvaluator(
        allowed_cross_tenant_pairs=(("tenant:a", "tenant:b"),)
    )
    findings = await ev.evaluate(
        _request(
            sender_tenant_id="tenant:a", recipient_tenant_id="tenant:b"
        )
    )
    assert len(findings) == 1
    assert findings[0].decision is CoordinationPolicyDecision.ANNOTATE


@pytest.mark.asyncio
async def test_tenant_isolation_allowlist_is_directional() -> None:
    """A→B on the allowlist must NOT also allow B→A."""
    ev = TenantIsolationEvaluator(
        allowed_cross_tenant_pairs=(("tenant:a", "tenant:b"),)
    )
    reverse = await ev.evaluate(
        _request(
            sender_tenant_id="tenant:b", recipient_tenant_id="tenant:a"
        )
    )
    assert len(reverse) == 1
    assert reverse[0].decision is CoordinationPolicyDecision.DENY
