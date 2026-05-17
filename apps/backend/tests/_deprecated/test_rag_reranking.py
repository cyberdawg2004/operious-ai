"""Sprint H — reranking substrate tests.

Properties pinned:

* `IdentityReranker` preserves input order exactly and reports correct
  input/output counts,
* the envelope shape (`is_ok`, `unwrap`, never raises) is honoured,
* `RerankerRegistry` rejects duplicates and unknown names.
"""

from __future__ import annotations

import uuid

import pytest

from app.rag.reranking.envelopes import RerankingEnvelope
from app.rag.reranking.identity import IdentityReranker
from app.rag.reranking.models import RerankingRequest
from app.rag.reranking.registry import RerankerRegistry
from app.rag.retrieval.models import RetrievalCandidate


def _candidate(score: float) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        ordinal=0,
        score=score,
        content=f"c-{score}",
        source=None,
        source_strategy="single_query",
        strategy_rank=0,
        metadata={},
    )


@pytest.mark.asyncio
async def test_identity_reranker_preserves_order_exactly() -> None:
    rer = IdentityReranker()
    cs = (_candidate(0.9), _candidate(0.1), _candidate(0.5))
    env = await rer.rerank(RerankingRequest(query="q", candidates=cs))
    assert isinstance(env, RerankingEnvelope)
    assert env.is_ok
    result = env.unwrap()
    assert result.candidates == cs
    assert result.input_count == 3
    assert result.output_count == 3
    assert result.reranker_name == "identity"
    assert env.trace.status == "ok"


@pytest.mark.asyncio
async def test_identity_reranker_handles_empty_input() -> None:
    rer = IdentityReranker()
    env = await rer.rerank(RerankingRequest(query="q", candidates=()))
    assert env.is_ok
    assert env.unwrap().candidates == ()


def test_reranker_registry_round_trip() -> None:
    reg = RerankerRegistry()
    reg.register(IdentityReranker())
    assert reg.has("identity")
    assert reg.names() == ("identity",)
    assert reg.get("identity").name == "identity"


def test_reranker_registry_rejects_duplicates() -> None:
    reg = RerankerRegistry()
    reg.register(IdentityReranker())
    with pytest.raises(ValueError):
        reg.register(IdentityReranker())


def test_reranker_registry_rejects_unknown_name() -> None:
    reg = RerankerRegistry()
    with pytest.raises(KeyError):
        reg.get("nonexistent")


def test_envelope_unwrap_raises_on_failure() -> None:
    from datetime import datetime, timezone
    from app.rag.reranking.tracing import RerankingTrace

    now = datetime.now(timezone.utc)
    env = RerankingEnvelope(
        trace=RerankingTrace(
            reranker_name="fake",
            status="failed",
            started_at=now,
            ended_at=now,
            latency_ms=0.0,
            input_count=0,
            output_count=0,
            error="boom",
        ),
        error=RuntimeError("boom"),
    )
    assert not env.is_ok
    with pytest.raises(RuntimeError):
        env.unwrap()
