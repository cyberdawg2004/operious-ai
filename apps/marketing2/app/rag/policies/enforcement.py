"""Policy enforcement — pure-function predicates.

Two seams the retrieval runtime + the budgeting pipeline call into:

* `candidate_matches_policy(candidate, policy) -> bool`
  Pure predicate: does this single candidate satisfy the policy?

* `filter_candidates_by_policy(candidates, policy) -> tuple[...]`
  Pure transformer: preserve input order, drop candidates that fail
  the predicate.

Both functions are referentially transparent — same input → same output.
The retrieval runtime is free to call them at multiple pipeline stages
(post-strategy, post-merge, pre-budget) without worrying about state.

The functions do NOT mutate; they do NOT log; they do NOT raise. A
policy that rejects every candidate produces an empty tuple — that is a
legitimate operational outcome, not a failure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from app.rag.policies.models import RetrievalPolicy

if TYPE_CHECKING:  # circular-import-safe
    from app.rag.retrieval.models import RetrievalCandidate


def candidate_matches_policy(
    candidate: "RetrievalCandidate",
    policy: RetrievalPolicy,
) -> bool:
    """Return True iff `candidate` satisfies every field of `policy`."""
    if policy.min_score is not None and candidate.score < policy.min_score:
        return False

    if policy.allowed_sources:
        source = candidate.source
        if source is None or source not in policy.allowed_sources:
            return False

    if policy.metadata_filter:
        # Conjunctive key-equality. The candidate carries the union of
        # vector-record metadata + chunk metadata; either may satisfy
        # the predicate, but in practice both should agree.
        meta = candidate.metadata
        for key, expected in policy.metadata_filter.items():
            if meta.get(key) != expected:
                return False

    return True


def filter_candidates_by_policy(
    candidates: Iterable["RetrievalCandidate"],
    policy: RetrievalPolicy,
) -> tuple["RetrievalCandidate", ...]:
    """Filter `candidates` against `policy` preserving input order.

    Returns a tuple (immutable) so the caller cannot accidentally mutate
    the result mid-pipeline.
    """
    return tuple(c for c in candidates if candidate_matches_policy(c, policy))


__all__ = [
    "candidate_matches_policy",
    "filter_candidates_by_policy",
]
