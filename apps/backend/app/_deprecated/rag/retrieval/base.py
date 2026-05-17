"""Retrieval strategy base contract.

Every retrieval shape (single-query today; hybrid, multi-source,
fan-out in future sprints) implements `BaseRetrievalStrategy.execute`.
The runtime treats strategies as **opaque candidate producers** — they
return a sequence of `RetrievalCandidate`s, the runtime takes ownership
of deduping, sorting, policy enforcement, and observability.

Architectural rules:
* a strategy is stateless across calls; per-request state lives in
  the request / context;
* a strategy may call into other services (`RetrievalService`,
  hypothetical hybrid retrieval, etc.) but MUST NOT mutate the vector
  provider or the database;
* a strategy raises on hard internal failures — the runtime catches
  and folds the error into an envelope. Returning empty is a legitimate
  outcome.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from app._deprecated.embeddings.tracing import EmbeddingTrace
from app._deprecated.rag.retrieval.models import (
    RetrievalCandidate,
    RetrievalRuntimeRequest,
    RetrievalStrategyInfo,
)


class StrategyExecutionResult:
    """Internal value returned by `BaseRetrievalStrategy.execute`.

    Carries the candidates produced + the optional embedding sub-trace
    the strategy observed. The runtime forwards the embedding trace
    into the runtime trace so downstream stages can reconstruct
    embedding lineage without re-reading the retrieval-service envelope.

    Defined as a regular class (not a frozen dataclass) so individual
    strategies can subclass when they need to carry richer auxiliary
    diagnostics in future sprints. Today the runtime only consumes the
    two public fields below.
    """

    __slots__ = ("candidates", "embedding_trace")

    def __init__(
        self,
        candidates: Sequence[RetrievalCandidate],
        embedding_trace: EmbeddingTrace | None = None,
    ) -> None:
        self.candidates = tuple(candidates)
        self.embedding_trace = embedding_trace


class BaseRetrievalStrategy(ABC):
    """Contract every retrieval strategy must implement."""

    info: RetrievalStrategyInfo

    @abstractmethod
    async def execute(
        self,
        request: RetrievalRuntimeRequest,
        *,
        request_id: str | None,
    ) -> StrategyExecutionResult:
        """Execute one retrieval invocation and return candidates."""


__all__ = [
    "BaseRetrievalStrategy",
    "StrategyExecutionResult",
]
