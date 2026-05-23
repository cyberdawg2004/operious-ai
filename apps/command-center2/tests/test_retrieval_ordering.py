"""Group A — retrieval ordering.

Verifies the foundational contract of the vector provider:

    same `(index_state, query_vector, top_k, filter)` → same hit order.

Specifically tests:

* Score-tied records are ordered by ascending UUID (deterministic tie break).
* Repeated execution against the same provider produces identical output.
* `top_k=0` returns an empty tuple, not an error.
* Empty filter and explicit-match filter behave as documented.

Failure condition: non-deterministic retrieval ordering. If this contract
breaks, retrieved context drifts between runs — which makes every
downstream AI-execution non-replayable.
"""

from __future__ import annotations

import uuid

import pytest

from app.providers.in_memory_vector_provider import InMemoryVectorProvider
from app.providers.vector_models import VectorQuery, VectorRecord


_INDEX = "ordering_test"


def _make_uuid(seed: int) -> uuid.UUID:
    """Reproducible UUIDs so test inputs are deterministic across machines."""

    return uuid.UUID(int=seed)


@pytest.mark.asyncio
async def test_query_ordering_is_repeatable(vector_provider: InMemoryVectorProvider) -> None:
    """Five consecutive queries against the same index return identical rows."""

    await vector_provider.ensure_index(_INDEX, dimensions=3)

    records = [
        VectorRecord(id=_make_uuid(1), vector=(1.0, 0.0, 0.0), metadata={"src": "a"}),
        VectorRecord(id=_make_uuid(2), vector=(0.9, 0.1, 0.0), metadata={"src": "b"}),
        VectorRecord(id=_make_uuid(3), vector=(0.5, 0.5, 0.0), metadata={"src": "c"}),
        VectorRecord(id=_make_uuid(4), vector=(0.0, 1.0, 0.0), metadata={"src": "d"}),
        VectorRecord(id=_make_uuid(5), vector=(0.0, 0.0, 1.0), metadata={"src": "e"}),
    ]
    await vector_provider.upsert(_INDEX, records)

    query = VectorQuery(vector=(1.0, 0.0, 0.0), top_k=5)

    first = await vector_provider.query(_INDEX, query)
    for _ in range(4):
        again = await vector_provider.query(_INDEX, query)
        assert len(again) == len(first)
        for a, b in zip(first, again):
            assert a.id == b.id
            assert a.score == b.score


@pytest.mark.asyncio
async def test_score_ties_resolve_by_ascending_uuid(
    vector_provider: InMemoryVectorProvider,
) -> None:
    """When several records score identically, ascending UUID breaks the tie.

    This is what makes the in-memory provider's output byte-stable across
    runs even on pathological inputs (duplicated vectors).
    """

    await vector_provider.ensure_index(_INDEX, dimensions=2)

    # Three records with identical vectors → identical cosine scores.
    # Insertion order is reversed to prove ordering is by id, not by insert.
    records = [
        VectorRecord(id=_make_uuid(30), vector=(1.0, 0.0), metadata={}),
        VectorRecord(id=_make_uuid(10), vector=(1.0, 0.0), metadata={}),
        VectorRecord(id=_make_uuid(20), vector=(1.0, 0.0), metadata={}),
    ]
    await vector_provider.upsert(_INDEX, records)

    hits = await vector_provider.query(
        _INDEX, VectorQuery(vector=(1.0, 0.0), top_k=10)
    )
    ids = [h.id for h in hits]
    assert ids == [_make_uuid(10), _make_uuid(20), _make_uuid(30)]


@pytest.mark.asyncio
async def test_scores_are_descending(vector_provider: InMemoryVectorProvider) -> None:
    """The contract is highest-score-first; verify monotonic non-increasing."""

    await vector_provider.ensure_index(_INDEX, dimensions=3)
    await vector_provider.upsert(
        _INDEX,
        [
            VectorRecord(id=_make_uuid(i), vector=(1.0, 0.1 * i, 0.0), metadata={})
            for i in range(1, 11)
        ],
    )

    hits = await vector_provider.query(
        _INDEX, VectorQuery(vector=(1.0, 0.0, 0.0), top_k=10)
    )
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_top_k_zero_returns_empty_tuple(
    vector_provider: InMemoryVectorProvider,
) -> None:
    """`top_k=0` is a valid, deterministic no-op."""

    await vector_provider.ensure_index(_INDEX, dimensions=2)
    await vector_provider.upsert(
        _INDEX,
        [VectorRecord(id=_make_uuid(1), vector=(1.0, 0.0))],
    )
    hits = await vector_provider.query(
        _INDEX, VectorQuery(vector=(1.0, 0.0), top_k=0)
    )
    assert hits == ()


@pytest.mark.asyncio
async def test_filter_is_conjunctive_equality(
    vector_provider: InMemoryVectorProvider,
) -> None:
    """`VectorQuery.filter` matches records whose metadata key-equals every entry."""

    await vector_provider.ensure_index(_INDEX, dimensions=2)
    await vector_provider.upsert(
        _INDEX,
        [
            VectorRecord(
                id=_make_uuid(1), vector=(1.0, 0.0), metadata={"tenant": "a", "type": "x"}
            ),
            VectorRecord(
                id=_make_uuid(2), vector=(1.0, 0.0), metadata={"tenant": "a", "type": "y"}
            ),
            VectorRecord(
                id=_make_uuid(3), vector=(1.0, 0.0), metadata={"tenant": "b", "type": "x"}
            ),
        ],
    )

    hits = await vector_provider.query(
        _INDEX,
        VectorQuery(
            vector=(1.0, 0.0),
            top_k=10,
            filter={"tenant": "a", "type": "x"},
        ),
    )
    assert [h.id for h in hits] == [_make_uuid(1)]


@pytest.mark.asyncio
async def test_zero_vector_query_returns_empty(
    vector_provider: InMemoryVectorProvider,
) -> None:
    """A zero query-vector has undefined cosine and returns empty deterministically."""

    await vector_provider.ensure_index(_INDEX, dimensions=2)
    await vector_provider.upsert(
        _INDEX,
        [VectorRecord(id=_make_uuid(1), vector=(1.0, 0.0))],
    )
    hits = await vector_provider.query(
        _INDEX, VectorQuery(vector=(0.0, 0.0), top_k=5)
    )
    assert hits == ()


@pytest.mark.asyncio
async def test_upsert_overwrites_by_id(
    vector_provider: InMemoryVectorProvider,
) -> None:
    """Upserting the same id replaces the existing record (not append)."""

    await vector_provider.ensure_index(_INDEX, dimensions=2)
    rid = _make_uuid(1)
    await vector_provider.upsert(_INDEX, [VectorRecord(id=rid, vector=(1.0, 0.0))])
    await vector_provider.upsert(_INDEX, [VectorRecord(id=rid, vector=(0.0, 1.0))])

    assert vector_provider.size(_INDEX) == 1
    hits = await vector_provider.query(
        _INDEX, VectorQuery(vector=(0.0, 1.0), top_k=1)
    )
    assert len(hits) == 1
    assert hits[0].id == rid
