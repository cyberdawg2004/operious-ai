"""Sprint H — budgeting determinism tests.

Properties pinned by these tests:

* `HeuristicTokenEstimator.estimate` is pure (same input → same output)
  and rejects bad config,
* `apply_budget` is deterministic for fixed input,
* every exclusion reason is exercised,
* per-document caps and chunk caps are greedy in input order,
* a candidate that exceeds the token budget alone is rejected; later
  candidates may still fit if they are cheaper (this is the documented
  greedy behaviour).
"""

from __future__ import annotations

import uuid

import pytest

from app.rag.budgeting.estimator import HeuristicTokenEstimator
from app.rag.budgeting.models import (
    BudgetConstraint,
    BudgetingDecisionReason,
)
from app.rag.budgeting.service import apply_budget
from app.rag.retrieval.models import RetrievalCandidate


def _candidate(
    *,
    content: str = "x",
    score: float = 0.9,
    document_id: uuid.UUID | None = None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=uuid.uuid4(),
        document_id=document_id or uuid.uuid4(),
        ordinal=0,
        score=score,
        content=content,
        source=None,
        source_strategy="single_query",
        strategy_rank=0,
        metadata={},
    )


# ─── HeuristicTokenEstimator ──────────────────────────────────────────


def test_heuristic_estimator_is_deterministic() -> None:
    est = HeuristicTokenEstimator(ratio=4)
    text = "operious ai context budgeting"
    assert est.estimate(text) == est.estimate(text)
    assert est.estimate("") == 0


def test_heuristic_estimator_min_one_token_for_short_text() -> None:
    est = HeuristicTokenEstimator(ratio=4)
    assert est.estimate("a") == 1
    assert est.estimate("ab") == 1
    assert est.estimate("abc") == 1
    assert est.estimate("abcd") == 1
    assert est.estimate("abcde") == 2


def test_heuristic_estimator_rejects_bad_ratio() -> None:
    with pytest.raises(ValueError):
        HeuristicTokenEstimator(ratio=0)
    with pytest.raises(ValueError):
        HeuristicTokenEstimator(ratio=-1)


# ─── apply_budget — basic determinism ─────────────────────────────────


def test_apply_budget_is_deterministic_for_fixed_input() -> None:
    estimator = HeuristicTokenEstimator(ratio=4)
    cs = [_candidate(content="abcd" * 5) for _ in range(3)]
    constraint = BudgetConstraint(max_tokens=10)
    a = apply_budget(cs, constraint, estimator)
    b = apply_budget(cs, constraint, estimator)
    assert a == b
    assert [d.reason for d in a.decisions] == [d.reason for d in b.decisions]


def test_apply_budget_preserves_input_order_in_decisions() -> None:
    estimator = HeuristicTokenEstimator(ratio=4)
    cs = [_candidate(content="aaaa"), _candidate(content="bbbb")]
    result = apply_budget(cs, BudgetConstraint(max_tokens=100), estimator)
    assert result.decisions[0].candidate is cs[0]
    assert result.decisions[1].candidate is cs[1]


# ─── Exclusion paths ──────────────────────────────────────────────────


def test_max_chunks_caps_count() -> None:
    estimator = HeuristicTokenEstimator(ratio=4)
    cs = [_candidate(content="a") for _ in range(5)]
    result = apply_budget(cs, BudgetConstraint(max_chunks=2), estimator)
    assert result.included_count == 2
    assert result.excluded_count == 3
    for d in result.decisions[:2]:
        assert d.reason is BudgetingDecisionReason.INCLUDED
    for d in result.decisions[2:]:
        assert d.reason is BudgetingDecisionReason.EXCEEDED_CHUNK_BUDGET


def test_max_chunks_per_doc_is_greedy_in_input_order() -> None:
    estimator = HeuristicTokenEstimator(ratio=4)
    doc_a = uuid.uuid4()
    doc_b = uuid.uuid4()
    cs = [
        _candidate(content="x", document_id=doc_a),  # 1 -> include
        _candidate(content="x", document_id=doc_a),  # 2 -> include
        _candidate(content="x", document_id=doc_a),  # 3 -> exclude (cap=2)
        _candidate(content="x", document_id=doc_b),  # 1 -> include
    ]
    result = apply_budget(
        cs, BudgetConstraint(max_chunks_per_doc=2), estimator
    )
    reasons = [d.reason for d in result.decisions]
    assert reasons == [
        BudgetingDecisionReason.INCLUDED,
        BudgetingDecisionReason.INCLUDED,
        BudgetingDecisionReason.EXCEEDED_PER_DOCUMENT_CAP,
        BudgetingDecisionReason.INCLUDED,
    ]


def test_max_tokens_rejects_candidates_that_overflow() -> None:
    estimator = HeuristicTokenEstimator(ratio=4)
    cs = [
        _candidate(content="abcd"),       # cost 1
        _candidate(content="abcdefgh"),   # cost 2
        _candidate(content="abcdefghij"),  # cost 3
    ]
    # Budget = 3. First (1) fits, second (1+2=3) fits, third would push to 6.
    result = apply_budget(cs, BudgetConstraint(max_tokens=3), estimator)
    assert [d.reason for d in result.decisions] == [
        BudgetingDecisionReason.INCLUDED,
        BudgetingDecisionReason.INCLUDED,
        BudgetingDecisionReason.EXCEEDED_TOKEN_BUDGET,
    ]
    assert result.total_tokens == 3


def test_min_score_floor_in_budgeting_independent_of_policy() -> None:
    estimator = HeuristicTokenEstimator(ratio=4)
    cs = [_candidate(content="x", score=0.4), _candidate(content="x", score=0.9)]
    result = apply_budget(cs, BudgetConstraint(min_score=0.5), estimator)
    assert result.decisions[0].reason is BudgetingDecisionReason.BELOW_MIN_SCORE
    assert result.decisions[1].reason is BudgetingDecisionReason.INCLUDED


def test_all_constraints_disabled_includes_everything() -> None:
    estimator = HeuristicTokenEstimator(ratio=4)
    cs = [_candidate(content="a"), _candidate(content="bb")]
    result = apply_budget(cs, BudgetConstraint(), estimator)
    assert result.included_count == 2
    assert result.excluded_count == 0
