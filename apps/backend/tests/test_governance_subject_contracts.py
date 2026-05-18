"""Sprint I Hardening — subject-contract enforcement tests.

Properties pinned:

* a policy whose `applicable_subject_kinds` excludes the evaluation's
  `subject.kind` is SKIPPED by the engine — no result produced, a
  `"skipped"` trace emitted with `skip_reason="subject_kind_not_applicable"`,
* a policy with an empty `applicable_subject_kinds` is INVOKED for
  every subject kind (backward compat for subject-kind-agnostic
  policies),
* `MaxQueryLengthPolicy` (RETRIEVAL only) is skipped for EXECUTION
  subjects,
* `ContentDenylistPolicy` (RETRIEVAL only) is skipped for EXECUTION
  subjects,
* the engine's skip behaviour is deterministic across runs,
* a chain that runs only skipped policies produces zero results,
  which the decision builder collapses to ALLOW (permissive default —
  the test pins this explicitly).
"""

from __future__ import annotations

from typing import ClassVar, FrozenSet, Sequence

import pytest

from app.governance.context import GovernanceContext
from app.governance.decisions import PolicyEvaluationResult, build_decision
from app.governance.enums import Decision, EnforcementStage, ViolationSeverity
from app.governance.evaluators.engine import PolicyEvaluationEngine
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.builtin import (
    ContentDenylistPolicy,
    MaxQueryLengthPolicy,
    TenantScopePolicy,
)
from app.governance.policies.chain import PolicyChain
from app.governance.subjects.base import (
    GenericGovernanceSubject,
    SubjectKind,
)
from app.governance.subjects.execution import ExecutionGovernanceSubject
from app.governance.subjects.retrieval import RetrievalGovernanceSubject


class _RetrievalOnlyPolicy(BaseGovernancePolicy):
    name = "retrieval_only"
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_RETRIEVAL}
    )
    applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
        {SubjectKind.RETRIEVAL}
    )

    async def evaluate(
        self, context: GovernanceContext
    ) -> Sequence[PolicyEvaluationResult]:
        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id="r",
                decision=Decision.DENY,  # would deny if invoked
                severity=ViolationSeverity.HIGH,
                reason="should never appear for non-retrieval subjects",
            ),
        )


class _SubjectAgnosticPolicy(BaseGovernancePolicy):
    name = "subject_agnostic"
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_RETRIEVAL}
    )
    # Empty applicable_subject_kinds = applies to any kind.
    applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset()

    async def evaluate(
        self, context: GovernanceContext
    ) -> Sequence[PolicyEvaluationResult]:
        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id="r",
                decision=Decision.ALLOW,
                reason="subject-kind-agnostic",
            ),
        )


def _chain(*policies: BaseGovernancePolicy) -> PolicyChain:
    return PolicyChain(
        chain_id="t.chain",
        stage=EnforcementStage.PRE_RETRIEVAL,
        policies=policies,
    )


def _ctx(subject) -> GovernanceContext:
    return GovernanceContext(
        stage=EnforcementStage.PRE_RETRIEVAL,
        action="rag.assemble_context",
        resource="r",
        request_id="req-1",
        subject=subject,
    )


# ─── Skip behaviour ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_policy_is_skipped_for_non_applicable_subject_kind() -> None:
    engine = PolicyEvaluationEngine()
    result = await engine.evaluate(
        _chain(_RetrievalOnlyPolicy()),
        _ctx(GenericGovernanceSubject()),
    )
    # No evaluation results produced; trace marked skipped.
    assert result.evaluation_results == ()
    assert len(result.policy_traces) == 1
    assert result.policy_traces[0].status == "skipped"
    assert (
        result.policy_traces[0].metadata.get("skip_reason")
        == "subject_kind_not_applicable"
    )


@pytest.mark.asyncio
async def test_policy_is_invoked_for_applicable_subject_kind() -> None:
    engine = PolicyEvaluationEngine()
    result = await engine.evaluate(
        _chain(_RetrievalOnlyPolicy()),
        _ctx(RetrievalGovernanceSubject(query="hi")),
    )
    assert len(result.evaluation_results) == 1
    assert result.evaluation_results[0].decision is Decision.DENY
    assert result.policy_traces[0].status == "ok"


@pytest.mark.asyncio
async def test_empty_applicable_kinds_means_subject_kind_agnostic() -> None:
    engine = PolicyEvaluationEngine()
    # GENERIC subject — the agnostic policy still runs.
    result = await engine.evaluate(
        _chain(_SubjectAgnosticPolicy()),
        _ctx(GenericGovernanceSubject()),
    )
    assert len(result.evaluation_results) == 1
    assert result.policy_traces[0].status == "ok"


# ─── Built-in policy applicability ────────────────────────────────────


@pytest.mark.asyncio
async def test_max_query_length_is_skipped_for_execution_subject() -> None:
    engine = PolicyEvaluationEngine()
    result = await engine.evaluate(
        _chain(MaxQueryLengthPolicy(max_length=10)),
        _ctx(ExecutionGovernanceSubject(query="hi")),
    )
    assert result.evaluation_results == ()
    assert result.policy_traces[0].status == "skipped"


@pytest.mark.asyncio
async def test_content_denylist_is_skipped_for_execution_subject() -> None:
    engine = PolicyEvaluationEngine()
    chain = PolicyChain(
        chain_id="post_retrieval.test",
        stage=EnforcementStage.POST_RETRIEVAL,
        policies=(ContentDenylistPolicy(denylist=("secret",)),),
    )
    ctx = GovernanceContext(
        stage=EnforcementStage.POST_RETRIEVAL,
        action="rag.assemble_context",
        resource="r",
        request_id="req-1",
        subject=ExecutionGovernanceSubject(query="hi"),
    )
    result = await engine.evaluate(chain, ctx)
    assert result.evaluation_results == ()
    assert result.policy_traces[0].status == "skipped"


@pytest.mark.asyncio
async def test_tenant_scope_applies_to_both_retrieval_and_execution() -> None:
    engine = PolicyEvaluationEngine()
    policy = TenantScopePolicy(allowed_tenants=frozenset({"acme"}))
    # Retrieval subject.
    result = await engine.evaluate(
        _chain(policy),
        _ctx(RetrievalGovernanceSubject(query="hi", tenant_id="acme")),
    )
    assert result.evaluation_results[0].decision is Decision.ALLOW
    # Execution subject.
    result = await engine.evaluate(
        _chain(policy),
        _ctx(ExecutionGovernanceSubject(query="hi", tenant_id="acme")),
    )
    assert result.evaluation_results[0].decision is Decision.ALLOW


# ─── Determinism ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skip_decision_is_deterministic_across_runs() -> None:
    engine = PolicyEvaluationEngine()
    chain = _chain(_RetrievalOnlyPolicy())
    ctx = _ctx(GenericGovernanceSubject())
    a = await engine.evaluate(chain, ctx)
    b = await engine.evaluate(chain, ctx)
    assert [t.status for t in a.policy_traces] == [t.status for t in b.policy_traces]
    assert a.evaluation_results == b.evaluation_results == ()


# ─── Empty-results aggregation ────────────────────────────────────────


@pytest.mark.asyncio
async def test_all_skipped_chain_collapses_to_fail_closed_deny() -> None:
    """Core Law 4 (Governance Determinism): when every policy in the
    chain is skipped (e.g., none applicable to the subject kind), the
    aggregation MUST fail closed. The substrate synthesises a DENY
    with `no_governance_evaluated` attribution rather than silently
    permitting the operation."""
    engine = PolicyEvaluationEngine()
    chain = _chain(_RetrievalOnlyPolicy())
    ctx = _ctx(GenericGovernanceSubject())
    result = await engine.evaluate(chain, ctx)
    decision = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id=chain.chain_id,
        evaluation_results=result.evaluation_results,
    )
    assert decision.decision is Decision.DENY
    assert len(decision.evaluated_rules) == 1
    assert (
        decision.evaluated_rules[0].rule_id
        == "no_governance_evaluated"
    )
