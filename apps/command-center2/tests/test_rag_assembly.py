"""Sprint H — context assembly integration tests.

Tests the full pipeline composition:

    retrieval runtime → reranker → budgeting → citations → grounding

through `ContextAssemblyService`. The retrieval runtime is composed
from fake strategies so the test isolates assembly-layer behaviour from
the embedding/vector chain (already covered by Sprint G tests).

Properties pinned:

* same request → byte-identical envelope (modulo trace timestamps),
* `ContextEnvelope` carries both `retrieval_envelope` and
  `reranking_envelope` on success,
* failed retrieval propagates `failed_stage="retrieval"` and a populated
  `retrieval_envelope`,
* policy overrides on `AssemblyRequest` are honoured,
* budget overrides on `AssemblyRequest` are honoured,
* citations + fragments + budgeting decisions stay aligned.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.config import Settings
from app.rag.assembly.envelopes import ContextEnvelope
from app.rag.assembly.models import AssemblyRequest
from app.rag.assembly.service import ContextAssemblyService
from app.rag.budgeting.estimator import HeuristicTokenEstimator
from app.rag.budgeting.models import BudgetConstraint
from app.rag.grounding.default import DefaultGroundingStrategy
from app.rag.policies.models import RetrievalPolicy
from app.rag.reranking.identity import IdentityReranker
from app.rag.reranking.registry import RerankerRegistry
from app.rag.retrieval.base import BaseRetrievalStrategy, StrategyExecutionResult
from app.rag.retrieval.models import (
    RetrievalCandidate,
    RetrievalRuntimeRequest,
    RetrievalStrategyInfo,
)
from app.rag.retrieval.runtime import RetrievalRuntime


# ─── Test doubles ─────────────────────────────────────────────────────


class _FixedStrategy(BaseRetrievalStrategy):
    def __init__(self, name: str, candidates: tuple[RetrievalCandidate, ...]) -> None:
        self.info = RetrievalStrategyInfo(name=name)
        self._candidates = candidates

    async def execute(self, request, *, request_id=None):  # type: ignore[override]
        return StrategyExecutionResult(candidates=self._candidates)


class _FailingStrategy(BaseRetrievalStrategy):
    info = RetrievalStrategyInfo(name="failing")

    async def execute(self, request, *, request_id=None):  # type: ignore[override]
        raise RuntimeError("strategy down")


# ─── Helpers ──────────────────────────────────────────────────────────


def _make_settings() -> Settings:
    import os

    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    os.environ.setdefault("OPENAI_API_KEY", "")
    return Settings()


def _candidate(
    *,
    chunk_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    score: float,
    content: str,
    source: str | None = None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id or uuid.uuid4(),
        document_id=document_id or uuid.uuid4(),
        ordinal=0,
        score=score,
        content=content,
        source=source,
        source_strategy="single_query",
        strategy_rank=0,
        metadata={},
    )


def _service_with(
    candidates: tuple[RetrievalCandidate, ...],
    *,
    strategy_name: str = "single_query",
    failing: bool = False,
) -> ContextAssemblyService:
    strategy: BaseRetrievalStrategy
    if failing:
        strategy = _FailingStrategy()
    else:
        strategy = _FixedStrategy(strategy_name, candidates)

    runtime = RetrievalRuntime(strategies={strategy.info.name: strategy})

    rer_registry = RerankerRegistry()
    rer_registry.register(IdentityReranker())

    grounding = {DefaultGroundingStrategy().name: DefaultGroundingStrategy()}

    return ContextAssemblyService(
        retrieval_runtime=runtime,
        reranker_registry=rer_registry,
        token_estimator=HeuristicTokenEstimator(ratio=4),
        grounding_strategies=grounding,
        settings=_make_settings(),
    )


# ─── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assembly_happy_path_produces_aligned_artefacts() -> None:
    cs = (
        _candidate(score=0.9, content="Alpha doc"),
        _candidate(score=0.7, content="Beta doc"),
    )
    service = _service_with(cs)
    env = await service.assemble(AssemblyRequest(query="hello"))

    assert isinstance(env, ContextEnvelope)
    assert env.is_ok
    ctx = env.unwrap()

    # Citations + fragments + included candidates aligned 1:1.
    assert ctx.citation_count == len(cs)
    assert ctx.fragment_count == len(cs)
    assert len(ctx.budgeting.included) == len(cs)
    for i, fragment in enumerate(ctx.grounding.fragments):
        assert fragment.citation_index == i + 1
        assert fragment.chunk_id == cs[i].chunk_id
        assert fragment.content == cs[i].content

    # Sub-envelopes preserved for replay.
    assert env.retrieval_envelope is not None
    assert env.retrieval_envelope.is_ok
    assert env.reranking_envelope is not None
    assert env.reranking_envelope.is_ok

    # Trace populated.
    assert env.trace.status == "ok"
    assert env.trace.candidate_count_post_retrieval == 2
    assert env.trace.candidate_count_post_rerank == 2
    assert env.trace.candidate_count_included == 2
    assert env.trace.candidate_count_excluded == 0
    assert env.trace.citation_count == 2
    assert env.trace.fragment_count == 2
    assert env.trace.reranker_name == "identity"
    assert env.trace.grounding_strategy == "default"


@pytest.mark.asyncio
async def test_assembly_is_deterministic_across_repeated_calls() -> None:
    cs = (
        _candidate(score=0.9, content="A" * 40),
        _candidate(score=0.7, content="B" * 40),
        _candidate(score=0.5, content="C" * 40),
    )
    service = _service_with(cs)
    env_a = await service.assemble(AssemblyRequest(query="hello"))
    env_b = await service.assemble(AssemblyRequest(query="hello"))
    ctx_a = env_a.unwrap()
    ctx_b = env_b.unwrap()
    # Ignore timestamps in traces; pin candidate / citation / fragment shape.
    assert [c.chunk_id for c in ctx_a.citation_index] == [
        c.chunk_id for c in ctx_b.citation_index
    ]
    assert [f.content for f in ctx_a.grounding.fragments] == [
        f.content for f in ctx_b.grounding.fragments
    ]
    assert ctx_a.budgeting.total_tokens == ctx_b.budgeting.total_tokens


@pytest.mark.asyncio
async def test_assembly_failed_retrieval_populates_retrieval_envelope() -> None:
    service = _service_with((), failing=True)
    env = await service.assemble(AssemblyRequest(query="hello"))
    assert not env.is_ok
    assert env.trace.status == "failed"
    assert env.trace.failed_stage == "retrieval"
    # Retrieval sub-envelope preserved even though it failed.
    assert env.retrieval_envelope is not None
    assert not env.retrieval_envelope.is_ok
    # Reranking never ran.
    assert env.reranking_envelope is None


@pytest.mark.asyncio
async def test_empty_query_fails_envelope_at_validation_stage() -> None:
    service = _service_with(())
    env = await service.assemble(AssemblyRequest(query="   "))
    assert not env.is_ok
    assert env.trace.failed_stage == "validation"


@pytest.mark.asyncio
async def test_policy_override_honoured() -> None:
    # Two candidates, one below the override min_score.
    cs = (
        _candidate(score=0.9, content="hi"),
        _candidate(score=0.2, content="lo"),
    )
    service = _service_with(cs)
    env = await service.assemble(
        AssemblyRequest(
            query="hello",
            policy=RetrievalPolicy(top_k=10, min_score=0.5),
        )
    )
    ctx = env.unwrap()
    assert ctx.citation_count == 1
    assert ctx.citation_index.by_index(1).chunk_id == cs[0].chunk_id


@pytest.mark.asyncio
async def test_budget_override_honoured() -> None:
    # Three candidates each costing 5 tokens (20 chars / 4 ratio).
    cs = (
        _candidate(score=0.9, content="A" * 20),
        _candidate(score=0.7, content="B" * 20),
        _candidate(score=0.5, content="C" * 20),
    )
    service = _service_with(cs)
    env = await service.assemble(
        AssemblyRequest(
            query="hello",
            budget=BudgetConstraint(max_tokens=10),
        )
    )
    ctx = env.unwrap()
    # First two fit (5 + 5 = 10); third would push to 15 -> excluded.
    assert ctx.budgeting.included_count == 2
    assert ctx.budgeting.excluded_count == 1
    assert ctx.citation_count == 2
    assert ctx.fragment_count == 2


@pytest.mark.asyncio
async def test_unknown_reranker_fails_at_reranking_stage() -> None:
    cs = (_candidate(score=0.9, content="a"),)
    service = _service_with(cs)
    env = await service.assemble(
        AssemblyRequest(query="hello", reranker="does-not-exist")
    )
    assert not env.is_ok
    assert env.trace.failed_stage == "reranking"
    assert env.retrieval_envelope is not None
    assert env.retrieval_envelope.is_ok  # retrieval succeeded
    assert env.reranking_envelope is None


@pytest.mark.asyncio
async def test_unknown_grounding_strategy_fails_at_grounding_stage() -> None:
    cs = (_candidate(score=0.9, content="a"),)
    service = _service_with(cs)
    env = await service.assemble(
        AssemblyRequest(query="hello", grounding_strategy="ghost")
    )
    assert not env.is_ok
    assert env.trace.failed_stage == "grounding"
    assert env.reranking_envelope is not None
    assert env.reranking_envelope.is_ok


@pytest.mark.asyncio
async def test_metadata_is_propagated_into_trace() -> None:
    cs = (_candidate(score=0.9, content="a"),)
    service = _service_with(cs)
    env = await service.assemble(
        AssemblyRequest(query="hello", metadata={"tenant": "acme"})
    )
    assert env.is_ok
    assert env.trace.metadata.get("tenant") == "acme"
