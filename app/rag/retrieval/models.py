"""Retrieval runtime data shapes.

`RetrievalCandidate` is the **lingua franca** of Sprint H — the type
that flows through retrieval → reranking → budgeting → citations →
grounding. Every downstream stage consumes immutable candidates and
produces an immutable derivative (a reranked sequence, a budgeting
result, a grounding result).

Why a richer type than `RetrievalHit`:

* candidates carry the producing strategy (`source_strategy`) so we can
  attribute the result back to whichever retrieval shape ran,
* candidates carry the original strategy-local rank, useful for
  hybrid-ranking experiments later,
* candidates carry the document `source` so `RetrievalPolicy.allowed_sources`
  can filter without re-querying the database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from app.rag.policies.models import RetrievalPolicy


@dataclass(frozen=True, slots=True)
class RetrievalStrategyInfo:
    """Identity + capability descriptor for a retrieval strategy."""

    name: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class RetrievalRuntimeRequest:
    """One end-to-end retrieval request handed to the runtime.

    Attributes:
        query:       Free-form text the user / caller wants to retrieve
                     against.
        policy:      Active retrieval policy. Defaults are applied at
                     the dependency-injection boundary; the runtime
                     does not reach for defaults itself.
        strategies:  Ordered tuple of strategy names to invoke. Order
                     is significant — it drives merge precedence on
                     duplicate candidates.
        metadata:    Opaque, propagated into the trace and into every
                     downstream stage's metadata.
    """

    query: str
    policy: RetrievalPolicy
    strategies: tuple[str, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    """One normalised retrieval candidate flowing through the pipeline.

    Attributes:
        chunk_id:        Stable identifier of the underlying chunk.
        document_id:     Document the chunk belongs to.
        ordinal:         Chunk position within the document (Sprint G
                         ingestion sets this).
        score:           Score reported by the producing strategy. The
                         pipeline treats higher = better uniformly.
        content:         Chunk text — included so downstream stages do
                         not need to re-fetch.
        source:          Optional `document.source` value, used by
                         policy filtering.
        source_strategy: Name of the strategy that produced this
                         candidate. On merge, the first strategy (in
                         request order) wins by default.
        strategy_rank:   0-based rank within the producing strategy.
        metadata:        Union of chunk metadata + vector-record
                         metadata, available for policy enforcement
                         and citation construction.
    """

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    ordinal: int
    score: float
    content: str
    source: str | None = None
    source_strategy: str = ""
    strategy_rank: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RetrievalCandidateSet:
    """Normalised, deterministic candidate set produced by the runtime.

    The runtime guarantees:

    * `candidates` is ordered `(score DESC, chunk_id ASC)`.
    * No duplicate `chunk_id` appears; on a duplicate the highest-score
      candidate wins, tie-broken by ascending UUID.
    * `strategy_attribution` maps each strategy name to the count of
      candidates it contributed to the **pre-dedup** pool, so audit /
      governance can see how each strategy performed.

    Attributes:
        candidates:             Final ordered, deduped candidate tuple.
        strategy_attribution:   Per-strategy contribution counts
                                (pre-dedup; useful for analytics).
        merged_from_strategies: Ordered tuple of every strategy that
                                produced at least one candidate, in
                                runtime invocation order.
    """

    candidates: tuple[RetrievalCandidate, ...]
    strategy_attribution: Mapping[str, int] = field(default_factory=dict)
    merged_from_strategies: tuple[str, ...] = ()

    def __len__(self) -> int:
        return len(self.candidates)

    @property
    def is_empty(self) -> bool:
        return len(self.candidates) == 0


__all__ = [
    "RetrievalStrategyInfo",
    "RetrievalRuntimeRequest",
    "RetrievalCandidate",
    "RetrievalCandidateSet",
]
