"""Sprint I — governance runtime tests.

Properties pinned:

* the runtime never raises; every outcome lands on a `GovernanceEnvelope`,
* an ALLOW decision produces a successful envelope with the AllowHandler
  outcome,
* a DENY decision produces a successful envelope (evaluation succeeded;
  verdict is DENY),
* a handler that raises produces a failed envelope BUT preserves the
  decision lineage,
* a stage without a configured chain produces a failed envelope with
  a `GovernanceConfigurationError`,
* the trace records the policy chain id, stage, action, resource,
  enforcement handler + outcome,
* repeated evaluations are deterministic (same input → same decision
  + traces),
* every Decision value is reachable through the runtime.
"""

from __future__ import annotations

from typing import ClassVar, FrozenSet, Sequence

import pytest

from app.governance.context import GovernanceContext
from app.governance.decisions import GovernanceDecision, PolicyEvaluationResult
from app.governance.enforcement.handlers import (
    AllowHandler,
    BaseEnforcementHandler,
    DegradeHandler,
    DenyHandler,
    EnforcementHandlerRegistry,
    EscalateHandler,
    RedactHandler,
    RequireApprovalHandler,
)
from app.governance.enforcement.models import EnforcementAction
from app.governance.enforcement.runtime import GovernanceRuntime
from app.governance.enums import Decision, EnforcementStage, ViolationSeverity
from app.governance.evaluators.engine import PolicyEvaluationEngine
from app.governance.exceptions import (
    EnforcementExecutionError,
    GovernanceConfigurationError,
)
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.chain import PolicyChain


class _FixedPolicy(BaseGovernancePolicy):
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_RETRIEVAL}
    )

    def __init__(self, policy_name: str, decision: Decision) -> None:
        self._name = policy_name
        self._decision = decision

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    async def evaluate(
        self, context: GovernanceContext
    ) -> Sequence[PolicyEvaluationResult]:
        return (
            PolicyEvaluationResult(
                policy_name=self._name,
                rule_id="rule",
                decision=self._decision,
                severity=ViolationSeverity.MEDIUM,
                reason="fixed",
            ),
        )


def _registry() -> EnforcementHandlerRegistry:
    reg = EnforcementHandlerRegistry()
    for handler in (
        AllowHandler(),
        DenyHandler(),
        RedactHandler(),
        DegradeHandler(),
        EscalateHandler(),
        RequireApprovalHandler(),
    ):
        reg.register(handler)
    return reg


def _runtime_with(
    policies: Sequence[BaseGovernancePolicy],
    *,
    handler_registry: EnforcementHandlerRegistry | None = None,
    stage: EnforcementStage = EnforcementStage.PRE_RETRIEVAL,
) -> GovernanceRuntime:
    chain = PolicyChain(
        chain_id="t.chain",
        stage=stage,
        policies=tuple(policies),
    )
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=handler_registry or _registry(),
        chains={stage: chain},
    )


def _ctx(
    *,
    stage: EnforcementStage = EnforcementStage.PRE_RETRIEVAL,
) -> GovernanceContext:
    from app.governance.subjects.base import GenericGovernanceSubject

    return GovernanceContext(
        stage=stage,
        action="rag.assemble_context",
        resource="tenant:t/resource:r",
        actor="system",
        tenant_id="t",
        request_id="req-1",
        subject=GenericGovernanceSubject(data={"query": "hello"}),
    )


# ─── Happy paths ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_allow_decision_produces_ok_envelope() -> None:
    runtime = _runtime_with([_FixedPolicy("p", Decision.ALLOW)])
    env = await runtime.evaluate(_ctx())
    assert env.is_ok
    decision = env.unwrap()
    assert decision.is_allow
    assert env.trace.status == "ok"
    assert env.trace.enforcement_handler == "allow"
    assert env.trace.policy_chain_id == "t.chain"


@pytest.mark.asyncio
async def test_deny_decision_produces_ok_envelope_with_deny_verdict() -> None:
    runtime = _runtime_with([_FixedPolicy("p", Decision.DENY)])
    env = await runtime.evaluate(_ctx())
    # IMPORTANT: is_ok is True because the EVALUATION succeeded. The
    # VERDICT is DENY — that is the working contract.
    assert env.is_ok
    decision = env.unwrap()
    assert decision.decision is Decision.DENY
    assert decision.is_blocking
    assert env.trace.enforcement_handler == "deny"


@pytest.mark.parametrize(
    "decision_value",
    [
        Decision.ALLOW,
        Decision.DENY,
        Decision.REDACT,
        Decision.DEGRADE,
        Decision.ESCALATE,
        Decision.REQUIRE_APPROVAL,
    ],
)
@pytest.mark.asyncio
async def test_every_decision_value_is_reachable_through_runtime(
    decision_value: Decision,
) -> None:
    runtime = _runtime_with([_FixedPolicy("p", decision_value)])
    env = await runtime.evaluate(_ctx())
    assert env.is_ok
    assert env.unwrap().decision is decision_value


# ─── Configuration failure ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_chain_for_stage_yields_failed_envelope() -> None:
    runtime = GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=_registry(),
        chains={},  # No chains configured at all.
    )
    env = await runtime.evaluate(_ctx())
    assert not env.is_ok
    assert isinstance(env.error, GovernanceConfigurationError)
    assert env.trace.status == "failed"


def test_incomplete_handler_registry_fails_at_composition_time() -> None:
    reg = EnforcementHandlerRegistry()
    reg.register(AllowHandler())  # Missing the other 5.
    with pytest.raises(GovernanceConfigurationError):
        GovernanceRuntime(
            engine=PolicyEvaluationEngine(),
            handler_registry=reg,
            chains={
                EnforcementStage.PRE_RETRIEVAL: PolicyChain(
                    chain_id="t.chain",
                    stage=EnforcementStage.PRE_RETRIEVAL,
                    policies=(_FixedPolicy("p", Decision.ALLOW),),
                ),
            },
        )


# ─── Handler-level failure preserves decision lineage ────────────────


class _RaisingHandler(BaseEnforcementHandler):
    decision = Decision.ALLOW
    name = "broken_allow"

    async def apply(self, decision: GovernanceDecision) -> EnforcementAction:
        raise RuntimeError("handler down")


@pytest.mark.asyncio
async def test_handler_failure_produces_failed_envelope_with_lineage() -> None:
    # Construct a registry where ALLOW handler raises.
    reg = EnforcementHandlerRegistry()
    reg.register(_RaisingHandler())
    for h in (
        DenyHandler(),
        RedactHandler(),
        DegradeHandler(),
        EscalateHandler(),
        RequireApprovalHandler(),
    ):
        reg.register(h)

    runtime = _runtime_with(
        [_FixedPolicy("p", Decision.ALLOW)],
        handler_registry=reg,
    )
    env = await runtime.evaluate(_ctx())
    assert not env.is_ok
    assert isinstance(env.error, EnforcementExecutionError)
    # The decision lineage is preserved on the exception.
    assert env.error.decision.decision is Decision.ALLOW
    assert env.error.handler_name == "broken_allow"
    # And on the trace.
    assert env.trace.status == "failed"
    assert env.trace.final_decision is Decision.ALLOW
    assert env.trace.enforcement_status == "failed"


# ─── Trace fidelity ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trace_records_chain_stage_action_resource_actor() -> None:
    runtime = _runtime_with([_FixedPolicy("p", Decision.ALLOW)])
    env = await runtime.evaluate(_ctx())
    trace = env.trace
    assert trace.policy_chain_id == "t.chain"
    assert trace.stage is EnforcementStage.PRE_RETRIEVAL
    assert trace.action == "rag.assemble_context"
    assert trace.resource == "tenant:t/resource:r"
    assert trace.actor == "system"
    assert trace.tenant_id == "t"


@pytest.mark.asyncio
async def test_trace_records_per_policy_counts() -> None:
    runtime = _runtime_with(
        [
            _FixedPolicy("p_allow", Decision.ALLOW),
            _FixedPolicy("p_redact", Decision.REDACT),
        ]
    )
    env = await runtime.evaluate(_ctx())
    assert env.trace.rule_count == 2
    assert env.trace.violation_count == 1  # The REDACT rule
    assert len(env.trace.policy_traces) == 2


# ─── Determinism / replay continuity ─────────────────────────────────


@pytest.mark.asyncio
async def test_runtime_decisions_are_deterministic_across_calls() -> None:
    runtime = _runtime_with(
        [
            _FixedPolicy("p1", Decision.ALLOW),
            _FixedPolicy("p2", Decision.DEGRADE),
        ]
    )
    a = await runtime.evaluate(_ctx())
    b = await runtime.evaluate(_ctx())
    assert a.unwrap().decision is b.unwrap().decision
    assert [
        r.decision for r in a.unwrap().evaluated_rules
    ] == [r.decision for r in b.unwrap().evaluated_rules]
    assert [t.policy_name for t in a.trace.policy_traces] == [
        t.policy_name for t in b.trace.policy_traces
    ]


# ─── Restriction-bearing decisions ───────────────────────────────────


class _RestrictivePolicy(BaseGovernancePolicy):
    """Emits a DEGRADE with a model restriction."""

    name = "restrictive"
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_RETRIEVAL}
    )

    async def evaluate(self, context: GovernanceContext):
        from app.governance.enums import RestrictionKind
        from app.governance.value_objects import RuntimeRestriction

        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id="downgrade_model",
                decision=Decision.DEGRADE,
                severity=ViolationSeverity.MEDIUM,
                reason="downgrade",
                restrictions=(
                    RuntimeRestriction(
                        kind=RestrictionKind.MODEL_RESTRICTION,
                        target="model:gpt-4o-mini",
                        value="restricted",
                        reason="cost ceiling",
                        policy_name=self.name,
                        rule_id="downgrade_model",
                    ),
                ),
            ),
        )


@pytest.mark.asyncio
async def test_runtime_propagates_restrictions_through_decision() -> None:
    runtime = _runtime_with([_RestrictivePolicy()])
    env = await runtime.evaluate(_ctx())
    decision = env.unwrap()
    assert decision.decision is Decision.DEGRADE
    assert len(decision.restrictions) == 1
    restriction = decision.restrictions[0]
    assert restriction.target == "model:gpt-4o-mini"
    assert env.trace.restriction_count == 1
