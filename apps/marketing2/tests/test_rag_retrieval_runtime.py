"""Sprint H — retrieval runtime tests.

These tests exercise the runtime against fake strategies (no embeddings,
no vector providers). The properties under test:

* deterministic ordering `(score DESC, chunk_id ASC)` after merge,
* dedup by `chunk_id` keeping highest-score candidate,
* multi-strategy fan-in preserves all unique candidates and produces
  correct strategy attribution,
* policy filter is applied AFTER merge / sort,
* invalid input (empty query, unknown strategy) produces a failed
  envelope without raising,
* all-strategies-failed produces a failed envelope; partial failures
  produce a success envelope with the trace recording each failure,
* the runtime emits one envelope per call and never raises.
"""

from __future__ import annotations

import uuid

import pytest

from app.rag.policies.models import RetrievalPolicy
from app.rag.retrieval.base import BaseRetrievalStrategy, StrategyExecutionResult
from app.rag.retrieval.envelopes import RetrievalRuntimeEnvelope
from app.rag.retrieval.models import (
    RetrievalCandidate,
    RetrievalRuntimeRequest,
    RetrievalStrategyInfo,
)
from app.rag.retrieval.runtime import RetrievalRuntime


# ─── Test doubles ─────────────────────────────────────────────────────


def _candidate(
    *,
    chunk_id: uuid.UUID | None = None,
    score: float,
    strategy: str = "fake",
    source: str | None = None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id or uuid.uuid4(),
        document_id=uuid.uuid4(),
        ordinal=0,
        score=score,
        content=f"c-{score}",
        source=source,
        source_strategy=strategy,
        strategy_rank=0,
        metadata={},
    )


class _StaticStrategy(BaseRetrievalStrategy):
    """A strategy that returns a fixed candidate list."""

    def __init__(self, name: str, candidates: tuple[RetrievalCandidate, ...]) -> None:
        self.info = RetrievalStrategyInfo(name=name, description="test")
        self._candidates = candidates

    async def execute(
        self,
        request: RetrievalRuntimeRequest,
        *,
        request_id: str | None = None,
    ) -> StrategyExecutionResult:
        # Rewrite source_strategy so the runtime can attribute correctly
        # regardless of how the fake candidates were constructed.
        rewritten = tuple(
            RetrievalCandidate(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                ordinal=c.ordinal,
                score=c.score,
                content=c.content,
                source=c.source,
                source_strategy=self.info.name,
                strategy_rank=i,
                metadata=c.metadata,
            )
            for i, c in enumerate(self._candidates)
        )
        return StrategyExecutionResult(candidates=rewritten)


class _FailingStrategy(BaseRetrievalStrategy):
    """A strategy that always raises."""

    def __init__(self, name: str) -> None:
        self.info = RetrievalStrategyInfo(name=name)

    async def execute(self, request, *, request_id=None):  # type: ignore[override]
        raise RuntimeError(f"{self.info.name} blew up")


# ─── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_strategy_returns_candidates_ordered_by_score_desc() -> None:
    cs = (
        _candidate(score=0.5),
        _candidate(score=0.9),
        _candidate(score=0.7),
    )
    runtime = RetrievalRuntime(strategies={"s": _StaticStrategy("s", cs)})
    env = await runtime.retrieve(
        RetrievalRuntimeRequest(
            query="q",
            policy=RetrievalPolicy(top_k=10),
            strategies=("s",),
        )
    )
    assert env.is_ok
    result = env.unwrap()
    scores = [c.score for c in result.candidates]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_ordering_breaks_ties_by_ascending_chunk_id() -> None:
    # Two candidates with identical scores — chunk_id must drive tiebreak.
    a = _candidate(score=0.5)
    b = _candidate(score=0.5)
    expected_first, expected_second = sorted((a, b), key=lambda c: str(c.chunk_id))
    runtime = RetrievalRuntime(strategies={"s": _StaticStrategy("s", (b, a))})
    env = await runtime.retrieve(
        RetrievalRuntimeRequest(
            query="q",
            policy=RetrievalPolicy(top_k=10),
            strategies=("s",),
        )
    )
    result = env.unwrap()
    assert result.candidates[0].chunk_id == expected_first.chunk_id
    assert result.candidates[1].chunk_id == expected_second.chunk_id


@pytest.mark.asyncio
async def test_multi_strategy_fan_in_dedups_keeping_highest_score() -> None:
    shared_chunk = uuid.uuid4()
    high = _candidate(chunk_id=shared_chunk, score=0.9, strategy="a")
    low = _candidate(chunk_id=shared_chunk, score=0.4, strategy="b")
    only_a = _candidate(score=0.8, strategy="a")
    only_b = _candidate(score=0.7, strategy="b")

    runtime = RetrievalRuntime(
        strategies={
            "a": _StaticStrategy("a", (high, only_a)),
            "b": _StaticStrategy("b", (low, only_b)),
        }
    )
    env = await runtime.retrieve(
        RetrievalRuntimeRequest(
            query="q",
            policy=RetrievalPolicy(top_k=10),
            strategies=("a", "b"),
        )
    )
    result = env.unwrap()
    # Dedup: shared_chunk appears once with the higher score.
    chunk_ids = [c.chunk_id for c in result.candidates]
    assert chunk_ids.count(shared_chunk) == 1
    # Highest-score copy wins.
    surviving = next(c for c in result.candidates if c.chunk_id == shared_chunk)
    assert surviving.score == 0.9
    # Final order is by score desc.
    scores = [c.score for c in result.candidates]
    assert scores == sorted(scores, reverse=True)
    # Strategy attribution counts pre-dedup contributions.
    assert result.strategy_attribution["a"] == 2
    assert result.strategy_attribution["b"] == 2


@pytest.mark.asyncio
async def test_runtime_is_deterministic_across_repeated_calls() -> None:
    cs = tuple(_candidate(score=0.9 - 0.1 * i) for i in range(5))
    runtime = RetrievalRuntime(strategies={"s": _StaticStrategy("s", cs)})
    req = RetrievalRuntimeRequest(
        query="q",
        policy=RetrievalPolicy(top_k=10),
        strategies=("s",),
    )
    env_a = await runtime.retrieve(req)
    env_b = await runtime.retrieve(req)
    a = env_a.unwrap().candidates
    b = env_b.unwrap().candidates
    assert tuple(c.chunk_id for c in a) == tuple(c.chunk_id for c in b)
    assert tuple(c.score for c in a) == tuple(c.score for c in b)


@pytest.mark.asyncio
async def test_policy_filter_applies_after_merge() -> None:
    cs = (_candidate(score=0.9), _candidate(score=0.4))
    runtime = RetrievalRuntime(strategies={"s": _StaticStrategy("s", cs)})
    env = await runtime.retrieve(
        RetrievalRuntimeRequest(
            query="q",
            policy=RetrievalPolicy(top_k=10, min_score=0.5),
            strategies=("s",),
        )
    )
    result = env.unwrap()
    assert len(result.candidates) == 1
    assert result.candidates[0].score == 0.9


@pytest.mark.asyncio
async def test_empty_query_fails_envelope_without_raising() -> None:
    runtime = RetrievalRuntime(strategies={"s": _StaticStrategy("s", ())})
    env = await runtime.retrieve(
        RetrievalRuntimeRequest(
            query="   ",
            policy=RetrievalPolicy(top_k=10),
            strategies=("s",),
        )
    )
    assert isinstance(env, RetrievalRuntimeEnvelope)
    assert not env.is_ok
    assert env.error is not None
    assert env.trace.status == "failed"


@pytest.mark.asyncio
async def test_unknown_strategy_fails_envelope_without_raising() -> None:
    runtime = RetrievalRuntime(strategies={"s": _StaticStrategy("s", ())})
    env = await runtime.retrieve(
        RetrievalRuntimeRequest(
            query="q",
            policy=RetrievalPolicy(top_k=10),
            strategies=("nope",),
        )
    )
    assert not env.is_ok
    assert "unknown" in str(env.error).lower()


@pytest.mark.asyncio
async def test_all_strategies_failed_returns_failed_envelope() -> None:
    runtime = RetrievalRuntime(
        strategies={
            "a": _FailingStrategy("a"),
            "b": _FailingStrategy("b"),
        }
    )
    env = await runtime.retrieve(
        RetrievalRuntimeRequest(
            query="q",
            policy=RetrievalPolicy(top_k=10),
            strategies=("a", "b"),
        )
    )
    assert not env.is_ok
    assert env.trace.status == "failed"
    # Both strategy invocations recorded.
    assert len(env.trace.strategy_traces) == 2
    assert all(t.status == "failed" for t in env.trace.strategy_traces)


@pytest.mark.asyncio
async def test_partial_failure_returns_success_with_partial_trace() -> None:
    cs = (_candidate(score=0.9),)
    runtime = RetrievalRuntime(
        strategies={
            "good": _StaticStrategy("good", cs),
            "bad": _FailingStrategy("bad"),
        }
    )
    env = await runtime.retrieve(
        RetrievalRuntimeRequest(
            query="q",
            policy=RetrievalPolicy(top_k=10),
            strategies=("good", "bad"),
        )
    )
    assert env.is_ok
    assert env.trace.status == "ok"
    statuses = {t.strategy: t.status for t in env.trace.strategy_traces}
    assert statuses == {"good": "ok", "bad": "failed"}


@pytest.mark.asyncio
async def test_no_strategies_named_in_request_fails_envelope() -> None:
    runtime = RetrievalRuntime(strategies={"s": _StaticStrategy("s", ())})
    env = await runtime.retrieve(
        RetrievalRuntimeRequest(
            query="q",
            policy=RetrievalPolicy(top_k=10),
            strategies=(),
        )
    )
    assert not env.is_ok
    assert "no strategies" in str(env.error).lower()
