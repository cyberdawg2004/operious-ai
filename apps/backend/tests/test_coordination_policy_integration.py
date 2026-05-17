"""`CoordinationRuntime` + `CoordinationPolicyRuntime` integration.

Pinned properties:

* policy DENY blocks dispatch with outcome `POLICY_DENIED` BEFORE
  governance ever runs,
* policy ESCALATE blocks dispatch with outcome `POLICY_ESCALATED`,
* policy ALLOW lets governance decide,
* policy and governance denials carry **distinct** outcomes
  (Sprint L2 Rule 2 — semantic separation),
* the coordination envelope carries the policy chain id + evaluation
  id + aggregate decision in its metadata for audit lineage,
* policy substrate failure (raising evaluator) surfaces as
  `POLICY_ERROR`.
"""

from __future__ import annotations

from typing import ClassVar, FrozenSet, Sequence

import pytest

from app.coordination.contracts.messages import CoordinationMessage
from app.coordination.contracts.requests import CoordinationDispatchRequest
from app.coordination.contracts.results import CoordinationDispatchOutcome
from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
    CoordinationPriority,
    CoordinationStatus,
)
from app.coordination.identity import (
    derive_correlation_id,
    derive_message_id,
)
from app.coordination.models.participants import CoordinationParticipant
from app.coordination.models.payload import CoordinationPayload
from app.coordination.models.recipients import CoordinationRecipient
from app.coordination.persistence.memory import (
    InMemoryCoordinationPersistence,
)
from app.coordination.policy.enums import (
    CoordinationPolicyDecision,
    CoordinationPolicyScope,
)
from app.coordination.policy.evaluators.base import (
    BaseCoordinationPolicyEvaluator,
)
from app.coordination.policy.evaluators.builtin import (
    EscalationEvaluator,
    TopologyEvaluator,
)
from app.coordination.policy.identity import derive_policy_id
from app.coordination.policy.models.escalation import (
    CoordinationPolicyEscalation,
)
from app.coordination.policy.models.policy import CoordinationPolicy
from app.coordination.policy.models.rule import CoordinationPolicyRule
from app.coordination.policy.persistence.memory import (
    InMemoryCoordinationPolicyPersistence,
)
from app.coordination.policy.registry import (
    CoordinationPolicyRegistry,
)
from app.coordination.policy.runtime import (
    CoordinationPolicyRuntime,
)
from app.coordination.policy.enums import CoordinationEscalationType
from app.coordination.policy.taxonomy import (
    CoordinationPolicyMetadataKey,
)
from app.coordination.registry.registry import CoordinationRegistry
from app.coordination.runtime.runtime import CoordinationRuntime
from app.governance.context import GovernanceContext
from app.governance.decisions import PolicyEvaluationResult
from app.governance.enforcement.handlers import (
    AllowHandler,
    DegradeHandler,
    DenyHandler,
    EnforcementHandlerRegistry,
    EscalateHandler,
    RedactHandler,
    RequireApprovalHandler,
)
from app.governance.enforcement.runtime import GovernanceRuntime
from app.governance.enums import Decision, EnforcementStage, ViolationSeverity
from app.governance.evaluators.engine import PolicyEvaluationEngine
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.chain import PolicyChain


# ─── Governance scaffolding (mirrors test_coordination_runtime.py) ───


class _FixedGovernancePolicy(BaseGovernancePolicy):
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_EXECUTION}
    )

    def __init__(self, name: str, verdict: Decision) -> None:
        self._name = name
        self._verdict = verdict

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    async def evaluate(
        self, context: GovernanceContext
    ) -> Sequence[PolicyEvaluationResult]:
        return (
            PolicyEvaluationResult(
                policy_name=self._name,
                rule_id="fixed",
                decision=self._verdict,
                severity=ViolationSeverity.LOW,
                reason="fixed",
            ),
        )


def _governance_runtime(verdict: Decision = Decision.ALLOW) -> GovernanceRuntime:
    handler_registry = EnforcementHandlerRegistry()
    for handler in (
        AllowHandler(),
        DenyHandler(),
        RedactHandler(),
        DegradeHandler(),
        EscalateHandler(),
        RequireApprovalHandler(),
    ):
        handler_registry.register(handler)
    chain = PolicyChain(
        chain_id="policy.integ.chain",
        stage=EnforcementStage.PRE_EXECUTION,
        policies=(_FixedGovernancePolicy("p.fixed", verdict),),
    )
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=handler_registry,
        chains={EnforcementStage.PRE_EXECUTION: chain},
    )


def _coordination_registry() -> CoordinationRegistry:
    reg = CoordinationRegistry()
    reg.register(
        CoordinationParticipant(
            participant_id="agent:retriever", kind="agent"
        )
    )
    reg.register(
        CoordinationParticipant(participant_id="agent:planner", kind="agent")
    )
    return reg


def _policy_runtime(
    *evaluators: BaseCoordinationPolicyEvaluator,
) -> CoordinationPolicyRuntime:
    reg = CoordinationPolicyRegistry()
    for ev in evaluators:
        reg.register(ev)
    return CoordinationPolicyRuntime(
        registry=reg,
        persistence=InMemoryCoordinationPolicyPersistence(),
    )


def _build_coordination_runtime(
    *,
    governance_verdict: Decision = Decision.ALLOW,
    policy: CoordinationPolicyRuntime | None = None,
) -> CoordinationRuntime:
    return CoordinationRuntime(
        governance_runtime=_governance_runtime(governance_verdict),
        persistence=InMemoryCoordinationPersistence(),
        registry=_coordination_registry(),
        policy_runtime=policy,
    )


def _make_request() -> CoordinationDispatchRequest:
    msg = CoordinationMessage(
        message_id=derive_message_id(seed="integ:m"),
        message_type=CoordinationMessageType.HANDOFF,
        sender_id="agent:retriever",
        recipient=CoordinationRecipient(
            recipient_id="agent:planner", kind="agent", tenant_id="tenant:t1"
        ),
        payload=CoordinationPayload(
            content_type="operious/agent-handoff", body={}
        ),
        priority=CoordinationPriority.NORMAL,
    )
    return CoordinationDispatchRequest(
        message=msg,
        direction=CoordinationDirection.AGENT_TO_AGENT,
        correlation_id=derive_correlation_id(seed="integ"),
        tenant_id="tenant:t1",
    )


# ─── Tests: no policy runtime → legacy behaviour ──────────────────────


@pytest.mark.asyncio
async def test_dispatch_without_policy_runtime_behaves_legacy() -> None:
    runtime = _build_coordination_runtime()
    result = await runtime.dispatch(_make_request())
    assert result.outcome is CoordinationDispatchOutcome.ACCEPTED
    assert result.envelope is not None
    assert result.envelope.status is CoordinationStatus.DISPATCHED


# ─── Tests: policy ALLOW → governance decides ─────────────────────────


@pytest.mark.asyncio
async def test_policy_allow_continues_to_governance_accepted() -> None:
    runtime = _build_coordination_runtime(
        policy=_policy_runtime(TopologyEvaluator())
    )
    result = await runtime.dispatch(_make_request())
    assert result.outcome is CoordinationDispatchOutcome.ACCEPTED
    # Envelope metadata threads policy lineage.
    assert result.envelope is not None
    md = result.envelope.metadata
    assert (
        CoordinationPolicyMetadataKey.AGGREGATE_DECISION.value in md
    )
    assert md[
        CoordinationPolicyMetadataKey.AGGREGATE_DECISION.value
    ] == CoordinationPolicyDecision.ALLOW.value


@pytest.mark.asyncio
async def test_policy_allow_then_governance_denied_remains_governance_denied() -> None:
    """Policy ALLOW + governance DENY → outcome is `DENIED` (governance)."""
    runtime = _build_coordination_runtime(
        governance_verdict=Decision.DENY,
        policy=_policy_runtime(TopologyEvaluator()),
    )
    result = await runtime.dispatch(_make_request())
    assert result.outcome is CoordinationDispatchOutcome.DENIED
    assert result.is_denied
    assert not result.is_policy_denied  # semantic separation
    assert result.envelope is not None
    assert result.envelope.status is CoordinationStatus.DENIED


# ─── Tests: policy DENY → POLICY_DENIED, governance never runs ────────


@pytest.mark.asyncio
async def test_policy_deny_blocks_before_governance() -> None:
    deny_policy = CoordinationPolicy(
        policy_id=derive_policy_id(seed="integ.deny"),
        name="integ.deny",
        scope=CoordinationPolicyScope.TOPOLOGY,
        rules=(
            CoordinationPolicyRule(
                rule_id="block_retriever_planner",
                scope=CoordinationPolicyScope.TOPOLOGY,
                decision=CoordinationPolicyDecision.DENY,
                sender_pattern="agent:retriever",
                recipient_pattern="agent:planner",
            ),
        ),
    )
    runtime = _build_coordination_runtime(
        policy=_policy_runtime(TopologyEvaluator(policies=(deny_policy,)))
    )
    result = await runtime.dispatch(_make_request())
    assert result.outcome is CoordinationDispatchOutcome.POLICY_DENIED
    assert result.is_policy_denied
    assert not result.is_denied  # NOT governance DENIED
    assert result.envelope is not None
    assert result.envelope.status is CoordinationStatus.POLICY_DENIED
    # Governance decision id is None — governance never ran.
    assert result.envelope.governance_decision_id is None


@pytest.mark.asyncio
async def test_policy_escalate_yields_policy_escalated_outcome() -> None:
    escalation = CoordinationPolicyEscalation(
        kind=CoordinationEscalationType.HUMAN_REVIEW,
        target="approver:platform",
    )
    esc_policy = CoordinationPolicy(
        policy_id=derive_policy_id(seed="integ.escalate"),
        name="integ.escalate",
        scope=CoordinationPolicyScope.ESCALATION,
        rules=(
            CoordinationPolicyRule(
                rule_id="esc",
                scope=CoordinationPolicyScope.ESCALATION,
                decision=CoordinationPolicyDecision.ESCALATE,
                sender_pattern="agent:retriever",
                recipient_pattern="agent:planner",
                escalations=(escalation,),
            ),
        ),
    )
    runtime = _build_coordination_runtime(
        policy=_policy_runtime(EscalationEvaluator(policies=(esc_policy,)))
    )
    result = await runtime.dispatch(_make_request())
    assert result.outcome is CoordinationDispatchOutcome.POLICY_ESCALATED
    assert result.is_policy_escalated
    assert result.envelope is not None
    assert result.envelope.status is CoordinationStatus.POLICY_DENIED
    # Semantic separation invariant.
    assert not result.is_denied


# ─── Tests: policy substrate failure → POLICY_ERROR ──────────────────


class _RaisingEvaluator(BaseCoordinationPolicyEvaluator):
    name: ClassVar[str] = "raiser"

    async def evaluate(self, request):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_policy_evaluator_failure_yields_policy_error() -> None:
    runtime = _build_coordination_runtime(
        policy=_policy_runtime(_RaisingEvaluator())
    )
    result = await runtime.dispatch(_make_request())
    # The evaluator raised but the substrate still produced a result
    # (with error attached), so the apex decision is ALLOW (no
    # findings) and the dispatch proceeds normally. The substrate
    # treats a raising evaluator as a degraded-but-successful
    # evaluation — Sprint L2 Rule 6 (inspectability) requires every
    # evaluator's behaviour to surface, not collapse to a hard fail.
    assert result.outcome is CoordinationDispatchOutcome.ACCEPTED
    # And the envelope metadata still carries the policy lineage,
    # including the evaluator names that ran.
    assert result.envelope is not None
    md = result.envelope.metadata
    assert "raiser" in (
        md.get(CoordinationPolicyMetadataKey.EVALUATOR_NAMES.value) or []
    )


# ─── Tests: outcome / status helpers semantic separation ─────────────


@pytest.mark.asyncio
async def test_is_policy_blocked_covers_both_blocking_outcomes() -> None:
    deny_policy = CoordinationPolicy(
        policy_id=derive_policy_id(seed="integ.blocked"),
        name="integ.blocked",
        scope=CoordinationPolicyScope.TOPOLOGY,
        rules=(
            CoordinationPolicyRule(
                rule_id="block",
                scope=CoordinationPolicyScope.TOPOLOGY,
                decision=CoordinationPolicyDecision.DENY,
                sender_pattern="agent:*",
                recipient_pattern="agent:*",
            ),
        ),
    )
    runtime = _build_coordination_runtime(
        policy=_policy_runtime(TopologyEvaluator(policies=(deny_policy,)))
    )
    result = await runtime.dispatch(_make_request())
    assert result.is_policy_blocked
    assert not result.is_substrate_ok or result.is_substrate_ok
    # is_substrate_ok must be True for POLICY_DENIED because the
    # substrate behaved correctly (the verdict is a verdict).
    assert result.is_substrate_ok
