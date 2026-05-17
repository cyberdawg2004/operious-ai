"""Sprint H — grounding tests.

Properties pinned:

* `DefaultGroundingStrategy` emits one fragment per candidate, in
  order,
* citation indices on fragments align 1:1 with the citation index,
* same input → byte-identical fragments,
* a candidate / citation-index length mismatch raises (the assembly
  pipeline guarantees alignment; this test pins the contract).
"""

from __future__ import annotations

import uuid

import pytest

from app.rag.citations.builder import build_citation_index
from app.rag.citations.models import CitationIndex
from app.rag.grounding.default import DefaultGroundingStrategy
from app.rag.retrieval.models import RetrievalCandidate


def _candidate(score: float, content: str) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        ordinal=0,
        score=score,
        content=content,
        source="src",
        source_strategy="single_query",
        strategy_rank=0,
        metadata={"k": "v"},
    )


def test_default_grounding_emits_one_fragment_per_candidate() -> None:
    cs = [_candidate(0.9, "A"), _candidate(0.8, "B")]
    idx = build_citation_index(cs)
    result = DefaultGroundingStrategy().build(cs, idx)
    assert len(result) == 2
    assert [f.citation_index for f in result] == [1, 2]
    assert [f.content for f in result] == ["A", "B"]
    assert [f.chunk_id for f in result] == [c.chunk_id for c in cs]


def test_default_grounding_is_deterministic() -> None:
    cs = [_candidate(0.9, "alpha"), _candidate(0.8, "beta")]
    idx = build_citation_index(cs)
    strategy = DefaultGroundingStrategy()
    a = strategy.build(cs, idx)
    b = strategy.build(cs, idx)
    assert a == b
    assert a.strategy_name == "default"


def test_default_grounding_raises_on_length_mismatch() -> None:
    cs = [_candidate(0.9, "A")]
    bad_idx = CitationIndex(citations=())  # zero citations vs 1 candidate
    with pytest.raises(ValueError):
        DefaultGroundingStrategy().build(cs, bad_idx)


def test_default_grounding_handles_empty_input() -> None:
    result = DefaultGroundingStrategy().build([], CitationIndex(citations=()))
    assert result.is_empty
