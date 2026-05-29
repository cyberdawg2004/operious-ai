"""Coordination critical-evaluator hardening."""

from __future__ import annotations

from typing import ClassVar, FrozenSet, Sequence

import pytest

from app.coordination.contracts.messages import CoordinationMessage
from app.coordination.contracts.requests import CoordinationDispatchRequest
from app.coordination.contracts.results import (
    CoordinationDispatchOutcome,
    CoordinationDispatchResult,
)
from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
    CoordinationPriority,
)
from app.coordination.identity import (
    derive_correlation_id,
    derive_message_id,
)
from app.coordination.models.participants import CoordinationParticipant
from app.coordination.models.payload import CoordinationPayload
from app.coordination.models.recipients import CoordinationRecipient
from app.coordination.persistence.memory import InMemoryCoordinationPersistence
from app.coordination.policy.enums import CoordinationPolicyDecision
from app.coordination.policy.evaluators.base import (
    BaseCoordinationPolicyEvaluator,
)
from app.coordination.policy.evaluators.builtin import (
    TenantIsolationEvaluator,
    TopologyEvaluator,
)
from app.coordination.policy.persistence.memory import (
    InMemoryCoordinationPolicyPersistence,
)
from app.coordination.policy.registry import CoordinationPolicyRegistry
from app.coordination.policy.runtime import CoordinationPolicyRuntime
from app.coordination.policy.taxonomy import CoordinationPolicyMetadataKey
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


class _FixedGovernancePolicy(BaseGovernancePolicy):
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_EXECUTION}
    )

    @property
    def name(self) -> str:  # type: ignore[override]
        return "p.allow"

    async def evaluate(
        self, context: GovernanceContext
    ) -> Sequence[PolicyEvaluationResult]:
        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id="fixed",
                decision=Decision.ALLOW,
                severity=ViolationSeverity.LOW,
                reason="fixed",
            ),
        )


def _governance_runtime() -> GovernanceRuntime:
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
        chain_id="coordination.hardening.chain",
        stage=EnforcementStage.PRE_EXECUTION,
        policies=(_FixedGovernancePolicy(),),
    )
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=handler_registry,
        chains={EnforcementStage.PRE_EXECUTION: chain},
    )


def _coordination_registry() -> CoordinationRegistry:
    registry = CoordinationRegistry()
    registry.register(
        CoordinationParticipant(
            participant_id="agent:retriever", kind="agent"
        )
    )
    registry.register(
        CoordinationParticipant(participant_id="agent:planner", kind="agent")
    )
    return registry


def _policy_runtime(
    *evaluators: BaseCoordinationPolicyEvaluator,
) -> CoordinationPolicyRuntime:
    registry = CoordinationPolicyRegistry()
    for evaluator in evaluators:
        registry.register(evaluator)
    return CoordinationPolicyRuntime(
        registry=registry,
        persistence=InMemoryCoordinationPolicyPersistence(),
    )


def _coordination_runtime(
    policy_runtime: CoordinationPolicyRuntime,
) -> CoordinationRuntime:
    return CoordinationRuntime(
        governance_runtime=_governance_runtime(),
        persistence=InMemoryCoordinationPersistence(),
        registry=_coordination_registry(),
        policy_runtime=policy_runtime,
    )


def _dispatch_request() -> CoordinationDispatchRequest:
    return CoordinationDispatchRequest(
        message=CoordinationMessage(
            message_id=derive_message_id(seed="aud1:m"),
            message_type=CoordinationMessageType.HANDOFF,
            sender_id="agent:retriever",
            recipient=CoordinationRecipient(
                recipient_id="agent:planner",
                kind="agent",
                tenant_id="tenant:t1",
            ),
            payload=CoordinationPayload(
                content_type="operious/agent-handoff",
                body={},
            ),
            priority=CoordinationPriority.NORMAL,
        ),
        direction=CoordinationDirection.AGENT_TO_AGENT,
        correlation_id=derive_correlation_id(seed="aud1"),
        tenant_id="tenant:t1",
    )


def _aggregate_decision(result: CoordinationDispatchResult) -> str:
    assert result.envelope is not None
    return str(
        result.envelope.metadata[
            CoordinationPolicyMetadataKey.AGGREGATE_DECISION.value
        ]
    )


def test_tenant_isolation_evaluator_is_critical() -> None:
    assert isinstance(TenantIsolationEvaluator.is_critical, bool)
    assert TenantIsolationEvaluator.is_critical is True


def test_topology_evaluator_not_critical() -> None:
    assert TopologyEvaluator.is_critical is False


@pytest.mark.asyncio
async def test_critical_evaluator_exception_synthesizes_deny(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _raise(*args: object, **kwargs: object):
        raise RuntimeError("tenant isolation unavailable")

    monkeypatch.setattr(TenantIsolationEvaluator, "evaluate", _raise)
    runtime = _coordination_runtime(
        _policy_runtime(TopologyEvaluator(), TenantIsolationEvaluator())
    )

    result = await runtime.dispatch(_dispatch_request())

    assert result.outcome is CoordinationDispatchOutcome.POLICY_DENIED
    assert result.is_policy_denied
    assert _aggregate_decision(result) == CoordinationPolicyDecision.DENY.value


@pytest.mark.asyncio
async def test_non_critical_evaluator_exception_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _raise(*args: object, **kwargs: object):
        raise RuntimeError("topology evaluator unavailable")

    monkeypatch.setattr(TopologyEvaluator, "evaluate", _raise)
    runtime = _coordination_runtime(
        _policy_runtime(TenantIsolationEvaluator(), TopologyEvaluator())
    )

    result = await runtime.dispatch(_dispatch_request())

    assert result.outcome is CoordinationDispatchOutcome.ACCEPTED
    assert _aggregate_decision(result) == CoordinationPolicyDecision.ALLOW.value


@pytest.mark.asyncio
async def test_empty_findings_allow_is_documented() -> None:
    runtime = _coordination_runtime(
        _policy_runtime(TenantIsolationEvaluator(), TopologyEvaluator())
    )

    result = await runtime.dispatch(_dispatch_request())

    assert result.outcome is CoordinationDispatchOutcome.ACCEPTED
    assert _aggregate_decision(result) == CoordinationPolicyDecision.ALLOW.value
