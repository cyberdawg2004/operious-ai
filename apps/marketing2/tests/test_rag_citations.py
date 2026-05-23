"""Sprint H — citation lineage tests.

`build_citation_index` is a pure function. Properties under test:

* citation indices are 1-based and strictly increasing,
* `len(citation_index)` matches input length,
* citation order mirrors input candidate order,
* lookups (`by_index`, `for_chunk`) return the right citation,
* two runs against the same candidates produce byte-identical output,
* out-of-range index lookups raise.
"""

from __future__ import annotations

import uuid

import pytest

from app.rag.citations.builder import build_citation_index
from app.rag.citations.models import Citation, CitationIndex
from app.rag.retrieval.models import RetrievalCandidate


def _candidate(score: float, source: str | None = None) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        ordinal=0,
        score=score,
        content=f"c-{score}",
        source=source,
        source_strategy="single_query",
        strategy_rank=0,
        metadata={"k": "v"},
    )


def test_citation_indices_are_one_based_and_aligned() -> None:
    cs = [_candidate(0.9), _candidate(0.8), _candidate(0.7)]
    idx = build_citation_index(cs)
    assert isinstance(idx, CitationIndex)
    assert len(idx) == 3
    assert [c.index for c in idx] == [1, 2, 3]
    for i, citation in enumerate(idx):
        assert isinstance(citation, Citation)
        assert citation.chunk_id == cs[i].chunk_id
        assert citation.document_id == cs[i].document_id
        assert citation.score == cs[i].score


def test_build_is_deterministic() -> None:
    cs = [_candidate(0.9), _candidate(0.8), _candidate(0.7)]
    a = build_citation_index(cs)
    b = build_citation_index(cs)
    assert a == b
    assert tuple(c.chunk_id for c in a) == tuple(c.chunk_id for c in b)


def test_by_index_lookup_returns_correct_citation() -> None:
    cs = [_candidate(0.9), _candidate(0.8)]
    idx = build_citation_index(cs)
    assert idx.by_index(1).chunk_id == cs[0].chunk_id
    assert idx.by_index(2).chunk_id == cs[1].chunk_id


def test_by_index_out_of_range_raises() -> None:
    cs = [_candidate(0.9)]
    idx = build_citation_index(cs)
    with pytest.raises(IndexError):
        idx.by_index(0)
    with pytest.raises(IndexError):
        idx.by_index(2)
    with pytest.raises(IndexError):
        idx.by_index(-1)


def test_for_chunk_returns_none_when_missing() -> None:
    cs = [_candidate(0.9)]
    idx = build_citation_index(cs)
    assert idx.for_chunk(cs[0].chunk_id).index == 1
    assert idx.for_chunk(uuid.uuid4()) is None


def test_empty_input_produces_empty_index() -> None:
    idx = build_citation_index([])
    assert idx.is_empty
    assert len(idx) == 0
