"""Retrieval policy contract.

A frozen, hashable, replay-friendly description of how a single
retrieval request should be constrained. Every field is explicit and
optional — the runtime defaults come from `Settings.RAG_DEFAULT_*` and
land on the policy at construction time.

Why a single policy type instead of N flags on the retrieval request:

* policies are reusable across requests (e.g., a tenant's standing
  retrieval profile);
* policies are inspectable as one unit (audit / governance);
* policies are hashable, so they survive caching layers later.

The policy is *enforced* by pure-function predicates in
`app.rag.policies.enforcement`. The policy itself contains no behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, FrozenSet, Mapping


def _empty_str_set() -> FrozenSet[str]:
    return frozenset()


def _empty_mapping() -> Mapping[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class RetrievalPolicy:
    """Per-request retrieval governance constraints.

    Attributes:
        top_k:                Max candidates a strategy may return.
        min_score:            Floor on per-candidate score (post-rank).
                              `None` means "no floor".
        max_chunks_per_doc:   Per-document chunk cap enforced during
                              budgeting. `None` means "no cap".
        allowed_sources:      Whitelist of `document.source` values.
                              Empty set means "no source filter".
        metadata_filter:      Conjunctive key-equality predicate over
                              chunk / candidate metadata. Mirrors the
                              vector provider's filter shape so the
                              policy is portable across backends.
        tenant_scope:         Optional tenant id propagated into traces
                              + audit events. Authentication of the
                              tenant value is a transport concern, not
                              a policy concern.
        policy_id:            Optional stable identifier so audit
                              records can correlate retrieval calls
                              against a known governance profile.
    """

    top_k: int = 8
    min_score: float | None = None
    max_chunks_per_doc: int | None = None
    allowed_sources: FrozenSet[str] = field(default_factory=_empty_str_set)
    metadata_filter: Mapping[str, Any] = field(default_factory=_empty_mapping)
    tenant_scope: str | None = None
    policy_id: str | None = None

    def __post_init__(self) -> None:
        if self.top_k < 0:
            raise ValueError(f"top_k must be >= 0, got {self.top_k}")
        if self.min_score is not None and not (-1.0 <= self.min_score <= 1.0):
            # Cosine range is [-1, 1]. The retrieval runtime today only
            # uses cosine; reject out-of-range floors at construction
            # rather than silently producing empty result sets.
            raise ValueError(
                f"min_score must be in [-1.0, 1.0], got {self.min_score}"
            )
        if self.max_chunks_per_doc is not None and self.max_chunks_per_doc < 0:
            raise ValueError(
                f"max_chunks_per_doc must be >= 0, got {self.max_chunks_per_doc}"
            )

    def with_overrides(
        self,
        *,
        top_k: int | None = None,
        metadata_filter: Mapping[str, Any] | None = None,
    ) -> "RetrievalPolicy":
        """Return a new policy with selected fields overridden.

        Used by the retrieval runtime when a caller wants to express
        a small adjustment ("same policy but top_k=20") without
        rebuilding the full object.
        """
        return RetrievalPolicy(
            top_k=top_k if top_k is not None else self.top_k,
            min_score=self.min_score,
            max_chunks_per_doc=self.max_chunks_per_doc,
            allowed_sources=self.allowed_sources,
            metadata_filter=(
                dict(metadata_filter) if metadata_filter is not None else dict(self.metadata_filter)
            ),
            tenant_scope=self.tenant_scope,
            policy_id=self.policy_id,
        )


__all__ = ["RetrievalPolicy"]
