"""Sprint H — retrieval policy enforcement tests.

The policy enforcement functions are pure. These tests pin down:

* `candidate_matches_policy` returns the correct boolean for every
  field of the policy,
* `filter_candidates_by_policy` preserves input order and returns an
  immutable tuple,
* policy validation rejects out-of-range inputs.
"""

from __future__ import annotations

import uuid

import pytest

from app.rag.policies.enforcement import (
    candidate_matches_policy,
    filter_candidates_by_policy,
)
from app.rag.policies.models import RetrievalPolicy
from app.rag.retrieval.models import RetrievalCandidate


def _make_candidate(
    *,
    score: float = 0.9,
    source: str | None = None,
    metadata: dict | None = None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        ordinal=0,
        score=score,
        content="hello",
        source=source,
        source_strategy="single_query",
        strategy_rank=0,
        metadata=metadata or {},
    )


def test_policy_rejects_negative_top_k() -> None:
    with pytest.raises(ValueError):
        RetrievalPolicy(top_k=-1)


def test_policy_rejects_out_of_range_min_score() -> None:
    with pytest.raises(ValueError):
        RetrievalPolicy(min_score=2.0)
    with pytest.raises(ValueError):
        RetrievalPolicy(min_score=-2.0)


def test_policy_rejects_negative_per_doc_cap() -> None:
    with pytest.raises(ValueError):
        RetrievalPolicy(max_chunks_per_doc=-1)


def test_min_score_filter_passes_when_unset() -> None:
    policy = RetrievalPolicy(top_k=5)
    candidate = _make_candidate(score=0.1)
    assert candidate_matches_policy(candidate, policy)


def test_min_score_filter_rejects_below_threshold() -> None:
    policy = RetrievalPolicy(top_k=5, min_score=0.5)
    assert not candidate_matches_policy(_make_candidate(score=0.4), policy)
    assert candidate_matches_policy(_make_candidate(score=0.5), policy)
    assert candidate_matches_policy(_make_candidate(score=0.51), policy)


def test_allowed_sources_filter() -> None:
    policy = RetrievalPolicy(
        top_k=5,
        allowed_sources=frozenset({"sops", "kbase"}),
    )
    assert candidate_matches_policy(_make_candidate(source="sops"), policy)
    assert candidate_matches_policy(_make_candidate(source="kbase"), policy)
    assert not candidate_matches_policy(_make_candidate(source="email"), policy)
    assert not candidate_matches_policy(_make_candidate(source=None), policy)


def test_metadata_filter_is_conjunctive() -> None:
    policy = RetrievalPolicy(
        top_k=5,
        metadata_filter={"tenant": "acme", "lang": "en"},
    )
    matches = _make_candidate(metadata={"tenant": "acme", "lang": "en"})
    missing_lang = _make_candidate(metadata={"tenant": "acme"})
    wrong_tenant = _make_candidate(metadata={"tenant": "globex", "lang": "en"})
    assert candidate_matches_policy(matches, policy)
    assert not candidate_matches_policy(missing_lang, policy)
    assert not candidate_matches_policy(wrong_tenant, policy)


def test_filter_preserves_input_order_and_returns_tuple() -> None:
    policy = RetrievalPolicy(top_k=10, min_score=0.5)
    a = _make_candidate(score=0.9)
    b = _make_candidate(score=0.3)
    c = _make_candidate(score=0.7)
    out = filter_candidates_by_policy([a, b, c], policy)
    assert isinstance(out, tuple)
    assert out == (a, c)


def test_filter_returns_empty_tuple_when_everything_rejected() -> None:
    policy = RetrievalPolicy(top_k=10, min_score=0.99)
    out = filter_candidates_by_policy(
        [_make_candidate(score=0.5), _make_candidate(score=0.7)],
        policy,
    )
    assert out == ()


def test_with_overrides_returns_new_instance() -> None:
    policy = RetrievalPolicy(top_k=5, policy_id="p1", tenant_scope="acme")
    new = policy.with_overrides(top_k=20)
    assert new is not policy
    assert new.top_k == 20
    assert new.policy_id == "p1"
    assert new.tenant_scope == "acme"
    assert policy.top_k == 5  # unmodified
