"""Deterministic context-budgeting pure function.

Algorithm — `apply_budget(candidates, constraint, estimator)`:

    decisions = []
    tokens = 0
    chunks = 0
    per_doc_counts = {}
    for candidate in candidates:          # iterate in input order
        cost = estimator.estimate(candidate.content)

        if min_score is set and candidate.score < min_score:
            reject (BELOW_MIN_SCORE)
        elif max_chunks is set and chunks >= max_chunks:
            reject (EXCEEDED_CHUNK_BUDGET)
        elif max_chunks_per_doc is set and per_doc_counts[doc] >= cap:
            reject (EXCEEDED_PER_DOCUMENT_CAP)
        elif max_tokens is set and tokens + cost > max_tokens:
            reject (EXCEEDED_TOKEN_BUDGET)
        else:
            accept (INCLUDED)
            tokens += cost
            chunks += 1
            per_doc_counts[doc] += 1

Properties:

* deterministic given a deterministic estimator,
* order-preserving (decisions[i].candidate == candidates[i]),
* exact (no off-by-one — `tokens + cost > max_tokens` is the predicate),
* per-document cap is enforced greedily — earlier candidates win,
* every input candidate is decided exactly once.
"""

from __future__ import annotations

import uuid
from typing import Iterable

from app._deprecated.rag.budgeting.estimator import BaseTokenEstimator
from app._deprecated.rag.budgeting.models import (
    BudgetConstraint,
    BudgetingDecision,
    BudgetingDecisionReason,
    BudgetingResult,
)
from app._deprecated.rag.retrieval.models import RetrievalCandidate


def apply_budget(
    candidates: Iterable[RetrievalCandidate],
    constraint: BudgetConstraint,
    estimator: BaseTokenEstimator,
) -> BudgetingResult:
    """Apply `constraint` to `candidates` greedily in input order."""
    decisions: list[BudgetingDecision] = []
    included: list[RetrievalCandidate] = []
    excluded: list[RetrievalCandidate] = []
    total_tokens = 0
    total_chunks = 0
    per_doc_counts: dict[uuid.UUID, int] = {}

    for candidate in candidates:
        cost = estimator.estimate(candidate.content)
        reason = _decide(
            candidate=candidate,
            cost=cost,
            constraint=constraint,
            total_tokens=total_tokens,
            total_chunks=total_chunks,
            per_doc_counts=per_doc_counts,
        )
        decisions.append(
            BudgetingDecision(
                candidate=candidate,
                reason=reason,
                estimated_tokens=cost,
            )
        )
        if reason is BudgetingDecisionReason.INCLUDED:
            included.append(candidate)
            total_tokens += cost
            total_chunks += 1
            per_doc_counts[candidate.document_id] = (
                per_doc_counts.get(candidate.document_id, 0) + 1
            )
        else:
            excluded.append(candidate)

    return BudgetingResult(
        constraint=constraint,
        decisions=tuple(decisions),
        included=tuple(included),
        excluded=tuple(excluded),
        total_tokens=total_tokens,
        included_count=len(included),
        excluded_count=len(excluded),
    )


def _decide(
    *,
    candidate: RetrievalCandidate,
    cost: int,
    constraint: BudgetConstraint,
    total_tokens: int,
    total_chunks: int,
    per_doc_counts: dict[uuid.UUID, int],
) -> BudgetingDecisionReason:
    """Return the decision reason for one candidate, given running totals."""
    if (
        constraint.min_score is not None
        and candidate.score < constraint.min_score
    ):
        return BudgetingDecisionReason.BELOW_MIN_SCORE

    if (
        constraint.max_chunks is not None
        and total_chunks >= constraint.max_chunks
    ):
        return BudgetingDecisionReason.EXCEEDED_CHUNK_BUDGET

    if constraint.max_chunks_per_doc is not None:
        if (
            per_doc_counts.get(candidate.document_id, 0)
            >= constraint.max_chunks_per_doc
        ):
            return BudgetingDecisionReason.EXCEEDED_PER_DOCUMENT_CAP

    if (
        constraint.max_tokens is not None
        and total_tokens + cost > constraint.max_tokens
    ):
        return BudgetingDecisionReason.EXCEEDED_TOKEN_BUDGET

    return BudgetingDecisionReason.INCLUDED


__all__ = ["apply_budget"]
