"""Reranking request / result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app._deprecated.rag.retrieval.models import RetrievalCandidate


@dataclass(frozen=True, slots=True)
class RerankingRequest:
    """Input to one reranker invocation.

    Attributes:
        query:       Original query text. Future ML rerankers will use
                     it; today's identity reranker ignores it.
        candidates:  Ordered candidates to rerank.
        metadata:    Opaque, propagated.
    """

    query: str
    candidates: tuple[RetrievalCandidate, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RerankingResult:
    """Successful output of one reranker invocation.

    Attributes:
        candidates:        Possibly reordered / annotated candidates.
                           Never invented.
        reranker_name:     Name of the reranker that produced this
                           result (for audit + replay attribution).
        input_count:       Candidate count BEFORE the reranker ran.
        output_count:      Candidate count AFTER the reranker ran.
                           For non-pruning rerankers, equals input_count.
    """

    candidates: tuple[RetrievalCandidate, ...]
    reranker_name: str
    input_count: int
    output_count: int


__all__ = ["RerankingRequest", "RerankingResult"]
