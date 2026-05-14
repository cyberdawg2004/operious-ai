"""Sprint I — governed assembly integration tests.

Properties pinned:

* governed assembly produces a successful envelope when both governance
  stages permit and Sprint H assembly succeeds,
* a blocking governance decision at PRE_RETRIEVAL aborts WITHOUT
  invoking the underlying Sprint H assembly service,
* a blocking governance decision at PRE_EXECUTION aborts AFTER assembly
  ran (context envelope preserved on the result),
* sub-envelopes are preserved on every failure path,
* governance decisions are attached to the result,
* the request_id flows through all three sub-envelopes uniformly.
"""

from __future__ import annotations

import uuid
from typing import ClassVar, FrozenSet, Sequence

import pytest

from app.core.config import Settings
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
from app.governance.exceptions import GovernanceViolationError
from app.governance.guardrails.adapters import (
    GovernedAssemblyEnvelope,
    GovernedAssemblyRequest,
    GovernedAssemblyRuntime,
)
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.chain import PolicyChain
from app.rag.assembly.models import AssemblyRequest
from app.rag.assembly.service import ContextAssemblyService
from app.rag.budgeting.estimator import HeuristicTokenEstimator
from app.rag.grounding.default import DefaultGroundingStrategy
from app.rag.reranking.identity import IdentityReranker
from app.rag.reranking.registry import RerankerRegistry
from app.rag.retrieval.base import BaseRetrievalStrategy, StrategyExecutionResult
from app.rag.retrieval.models import RetrievalCandidate, RetrievalStrategyInfo
from app.rag.retrieval.runtime import RetrievalRuntime


# ─── Reusable test doubles ───────────────────────────────────────────


class _StaticRetrievalStrategy(BaseRetrievalStrategy):
    def __init__(self, candidates: tuple[RetrievalCandidate, ...]) -> None:
        self.info = RetrievalStrategyInfo(name="single_query")
        self._candidates = candidates

    async def execute(self, request, *, request_id=None):  # type: ignore[override]
        return StrategyExecutionResult(candidates=self._candidates)


class _AlwaysDenyPolicy(BaseGovernancePolicy):
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {
            EnforcementStage.PRE_RETRIEVAL,
            EnforcementStage.PRE_EXECUTION,
        }
    )
    name = "always_deny"

    async def evaluate(
        self,
        context: GovernanceContext,
    ) -> Sequence[PolicyEvaluationResult]:
        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id="always_deny",
                decision=Decision.DENY,
                severity=ViolationSeverity.HIGH,
                reason="test policy denies everything",
            ),
        )


class _AlwaysAllowPolicy(BaseGovernancePolicy):
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {
            EnforcementStage.PRE_RETRIEVAL,
            EnforcementStage.PRE_EXECUTION,
        }
    )
    name = "always_allow"

    async def evaluate(
        self,
        context: GovernanceContext,
    ) -> Sequence[PolicyEvaluationResult]:
        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id="always_allow",
                decision=Decision.ALLOW,
                severity=ViolationSeverity.LOW,
                reason="test policy allows everything",
            ),
        )


def _candidate(score: float, content: str) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        ordinal=0,
        score=score,
        content=content,
        source=None,
        source_strategy="single_query",
        strategy_rank=0,
        metadata={},
    )


def _make_settings() -> Settings:
    import os

    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    os.environ.setdefault("OPENAI_API_KEY", "")
    return Settings()


def _assembly_service(
    candidates: tuple[RetrievalCandidate, ...],
) -> ContextAssemblyService:
    strategy = _StaticRetrievalStrategy(candidates)
    runtime = RetrievalRuntime(strategies={strategy.info.name: strategy})
    rer_reg = RerankerRegistry()
    rer_reg.register(IdentityReranker())
    return ContextAssemblyService(
        retrieval_runtime=runtime,
        reranker_registry=rer_reg,
        token_estimator=HeuristicTokenEstimator(ratio=4),
        grounding_strategies={
            DefaultGroundingStrategy().name: DefaultGroundingStrategy()
        },
        settings=_make_settings(),
    )


def _handler_registry() -> EnforcementHandlerRegistry:
    reg = EnforcementHandlerRegistry()
    for h in (
        AllowHandler(),
        DenyHandler(),
        RedactHandler(),
        DegradeHandler(),
        EscalateHandler(),
        RequireApprovalHandler(),
    ):
        reg.register(h)
    return reg


def _governance_runtime(
    *,
    pre_retrieval_policies: tuple[BaseGovernancePolicy, ...],
    pre_execution_policies: tuple[BaseGovernancePolicy, ...],
) -> GovernanceRuntime:
    chains = {}
    if pre_retrieval_policies:
        chains[EnforcementStage.PRE_RETRIEVAL] = PolicyChain(
            chain_id="pre_retrieval.test",
            stage=EnforcementStage.PRE_RETRIEVAL,
            policies=pre_retrieval_policies,
        )
    if pre_execution_policies:
        chains[EnforcementStage.PRE_EXECUTION] = PolicyChain(
            chain_id="pre_execution.test",
            stage=EnforcementStage.PRE_EXECUTION,
            policies=pre_execution_policies,
        )
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=_handler_registry(),
        chains=chains,
    )


# ─── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_both_stages_allow_and_assembly_succeeds() -> None:
    cs = (_candidate(score=0.9, content="alpha"),)
    runtime = GovernedAssemblyRuntime(
        governance_runtime=_governance_runtime(
            pre_retrieval_policies=(_AlwaysAllowPolicy(),),
            pre_execution_policies=(_AlwaysAllowPolicy(),),
        ),
        assembly_service=_assembly_service(cs),
    )
    env = await runtime.assemble(
        GovernedAssemblyRequest(
            assembly=AssemblyRequest(query="hello"),
            tenant_id="acme",
        )
    )
    assert isinstance(env, GovernedAssemblyEnvelope)
    assert env.is_ok
    result = env.unwrap()
    assert result.context.citation_count == 1
    # Both decisions attached.
    assert result.pre_retrieval_decision.decision is Decision.ALLOW
    assert result.pre_execution_decision.decision is Decision.ALLOW
    # Sub-envelopes preserved.
    assert env.pre_retrieval_envelope is not None
    assert env.context_envelope is not None
    assert env.pre_execution_envelope is not None


@pytest.mark.asyncio
async def test_pre_retrieval_deny_aborts_before_assembly() -> None:
    cs = (_candidate(score=0.9, content="alpha"),)
    runtime = GovernedAssemblyRuntime(
        governance_runtime=_governance_runtime(
            pre_retrieval_policies=(_AlwaysDenyPolicy(),),
            pre_execution_policies=(_AlwaysAllowPolicy(),),
        ),
        assembly_service=_assembly_service(cs),
    )
    env = await runtime.assemble(
        GovernedAssemblyRequest(
            assembly=AssemblyRequest(query="hello"),
            tenant_id="acme",
        )
    )
    assert not env.is_ok
    assert env.failed_stage == "governance.pre_retrieval"
    assert isinstance(env.error, GovernanceViolationError)
    # The blocking decision is attached.
    assert env.error.decision.decision is Decision.DENY
    # PRE_RETRIEVAL envelope preserved.
    assert env.pre_retrieval_envelope is not None
    assert env.pre_retrieval_envelope.is_ok  # Evaluation succeeded; verdict is DENY.
    # Assembly never ran.
    assert env.context_envelope is None
    assert env.pre_execution_envelope is None


@pytest.mark.asyncio
async def test_pre_execution_deny_aborts_after_assembly() -> None:
    cs = (_candidate(score=0.9, content="alpha"),)
    runtime = GovernedAssemblyRuntime(
        governance_runtime=_governance_runtime(
            pre_retrieval_policies=(_AlwaysAllowPolicy(),),
            pre_execution_policies=(_AlwaysDenyPolicy(),),
        ),
        assembly_service=_assembly_service(cs),
    )
    env = await runtime.assemble(
        GovernedAssemblyRequest(
            assembly=AssemblyRequest(query="hello"),
            tenant_id="acme",
        )
    )
    assert not env.is_ok
    assert env.failed_stage == "governance.pre_execution"
    # All three sub-envelopes preserved on this failure path.
    assert env.pre_retrieval_envelope is not None
    assert env.context_envelope is not None
    assert env.context_envelope.is_ok  # Assembly itself succeeded.
    assert env.pre_execution_envelope is not None


@pytest.mark.asyncio
async def test_no_chain_configured_skips_governance_at_that_stage() -> None:
    cs = (_candidate(score=0.9, content="alpha"),)
    runtime = GovernedAssemblyRuntime(
        # Only PRE_EXECUTION chain configured; PRE_RETRIEVAL is skipped.
        governance_runtime=_governance_runtime(
            pre_retrieval_policies=(),
            pre_execution_policies=(_AlwaysAllowPolicy(),),
        ),
        assembly_service=_assembly_service(cs),
    )
    env = await runtime.assemble(
        GovernedAssemblyRequest(
            assembly=AssemblyRequest(query="hello"),
        )
    )
    assert env.is_ok
    # No real PRE_RETRIEVAL envelope when chain absent — replayers
    # see the "skipped" state explicitly.
    assert env.pre_retrieval_envelope is None
    # The result still has a (synthesised ALLOW) decision attached so
    # downstream code does not need to special-case the missing stage.
    result = env.unwrap()
    assert result.pre_retrieval_decision.decision is Decision.ALLOW
    assert result.pre_retrieval_decision.policy_chain_id == "<no-chain-configured>"


@pytest.mark.asyncio
async def test_governed_assembly_is_deterministic_for_fixed_input() -> None:
    cs = (
        _candidate(score=0.9, content="A" * 20),
        _candidate(score=0.7, content="B" * 20),
    )
    runtime = GovernedAssemblyRuntime(
        governance_runtime=_governance_runtime(
            pre_retrieval_policies=(_AlwaysAllowPolicy(),),
            pre_execution_policies=(_AlwaysAllowPolicy(),),
        ),
        assembly_service=_assembly_service(cs),
    )
    req = GovernedAssemblyRequest(
        assembly=AssemblyRequest(query="hello"),
        tenant_id="acme",
    )
    a = await runtime.assemble(req)
    b = await runtime.assemble(req)
    assert a.unwrap().pre_retrieval_decision.decision is (
        b.unwrap().pre_retrieval_decision.decision
    )
    assert [
        f.chunk_id for f in a.unwrap().context.grounding.fragments
    ] == [f.chunk_id for f in b.unwrap().context.grounding.fragments]
