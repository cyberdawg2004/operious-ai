"""Sprint I — policy evaluation engine tests.

Properties pinned:

* the engine runs policies in chain declared order,
* a policy that raises produces a synthetic DENY with critical
  severity (fail-safe),
* per-policy traces are produced for every policy in order,
* total order of evaluation_results matches chain declaration,
* engine output is deterministic for fixed input.
"""

from __future__ import annotations

from typing import ClassVar, FrozenSet, Sequence

import pytest

from app.governance.context import GovernanceContext
from app.governance.decisions import PolicyEvaluationResult
from app.governance.enums import Decision, EnforcementStage, ViolationSeverity
from app.governance.evaluators.engine import PolicyEvaluationEngine
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.chain import PolicyChain


class _FixedPolicy(BaseGovernancePolicy):
    """Policy that returns a fixed decision per evaluate() call."""

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
                severity=ViolationSeverity.LOW,
                reason="fixed",
            ),
        )


class _RaisingPolicy(BaseGovernancePolicy):
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_RETRIEVAL}
    )

    def __init__(self, policy_name: str) -> None:
        self._name = policy_name

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    async def evaluate(
        self, context: GovernanceContext
    ) -> Sequence[PolicyEvaluationResult]:
        raise RuntimeError("boom")


def _ctx() -> GovernanceContext:
    from app.governance.subjects.base import GenericGovernanceSubject

    return GovernanceContext(
        stage=EnforcementStage.PRE_RETRIEVAL,
        action="rag.assemble_context",
        resource="r",
        tenant_id="t",
        request_id="req-1",
        subject=GenericGovernanceSubject(data={"query": "hello"}),
    )


def _chain(*policies: BaseGovernancePolicy) -> PolicyChain:
    return PolicyChain(
        chain_id="test.chain",
        stage=EnforcementStage.PRE_RETRIEVAL,
        policies=policies,
    )


@pytest.mark.asyncio
async def test_engine_runs_policies_in_declared_order() -> None:
    chain = _chain(
        _FixedPolicy("a", Decision.ALLOW),
        _FixedPolicy("b", Decision.REDACT),
        _FixedPolicy("c", Decision.DEGRADE),
    )
    result = await PolicyEvaluationEngine().evaluate(chain, _ctx())
    # Traces preserve declaration order.
    assert [t.policy_name for t in result.policy_traces] == ["a", "b", "c"]
    # Evaluation results preserve declaration order too.
    assert [r.policy_name for r in result.evaluation_results] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_raising_policy_produces_synthetic_deny_with_critical_severity() -> None:
    chain = _chain(
        _FixedPolicy("a", Decision.ALLOW),
        _RaisingPolicy("b"),
        _FixedPolicy("c", Decision.ALLOW),
    )
    result = await PolicyEvaluationEngine().evaluate(chain, _ctx())
    assert len(result.evaluation_results) == 3  # a + synthetic + c
    bad = result.evaluation_results[1]
    assert bad.policy_name == "b"
    assert bad.decision is Decision.DENY
    assert bad.severity is ViolationSeverity.CRITICAL
    assert bad.rule_id == "evaluation_error"
    # Trace marks failure.
    bad_trace = result.policy_traces[1]
    assert bad_trace.status == "failed"
    assert "boom" in (bad_trace.error or "")


@pytest.mark.asyncio
async def test_engine_output_is_deterministic_for_fixed_input() -> None:
    chain = _chain(
        _FixedPolicy("a", Decision.ALLOW),
        _FixedPolicy("b", Decision.DEGRADE),
    )
    ctx = _ctx()
    engine = PolicyEvaluationEngine()
    a = await engine.evaluate(chain, ctx)
    b = await engine.evaluate(chain, ctx)
    assert [r.decision for r in a.evaluation_results] == [
        r.decision for r in b.evaluation_results
    ]
    assert [t.policy_name for t in a.policy_traces] == [
        t.policy_name for t in b.policy_traces
    ]


@pytest.mark.asyncio
async def test_empty_chain_produces_no_results_and_no_traces() -> None:
    chain = _chain()
    result = await PolicyEvaluationEngine().evaluate(chain, _ctx())
    assert result.evaluation_results == ()
    assert result.policy_traces == ()


@pytest.mark.asyncio
async def test_chain_aggregation_order_does_not_affect_final_decision() -> None:
    """Most-restrictive wins regardless of declaration order."""
    from app.governance.decisions import build_decision

    # Two chains with same policies in different order; final decision
    # must be identical.
    p_allow = _FixedPolicy("a", Decision.ALLOW)
    p_redact = _FixedPolicy("b", Decision.REDACT)
    p_deny = _FixedPolicy("c", Decision.DENY)

    engine = PolicyEvaluationEngine()
    res_a = await engine.evaluate(_chain(p_allow, p_redact, p_deny), _ctx())
    res_b = await engine.evaluate(_chain(p_deny, p_allow, p_redact), _ctx())

    decision_a = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id="t",
        evaluation_results=res_a.evaluation_results,
    )
    decision_b = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id="t",
        evaluation_results=res_b.evaluation_results,
    )
    assert decision_a.decision is decision_b.decision is Decision.DENY
