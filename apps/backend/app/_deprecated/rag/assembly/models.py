"""Context assembly data shapes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app._deprecated.rag.budgeting.models import BudgetConstraint, BudgetingResult
from app._deprecated.rag.citations.models import CitationIndex
from app._deprecated.rag.grounding.models import GroundingResult
from app._deprecated.rag.policies.models import RetrievalPolicy
from app._deprecated.rag.retrieval.models import RetrievalCandidateSet


@dataclass(frozen=True, slots=True)
class AssemblyRequest:
    """One end-to-end context-assembly request.

    Attributes:
        query:         Free-form query text.
        policy:        Active retrieval policy. Optional — when omitted
                       the service applies its DI-injected default.
        budget:        Active budget constraint. Optional — when
                       omitted the service applies its DI-injected
                       default.
        strategies:    Ordered tuple of retrieval-strategy names.
                       Optional — when omitted the service applies
                       its DI-injected default singleton.
        reranker:      Optional reranker name. When omitted the service
                       applies the DI-injected default (typically
                       `identity`).
        grounding_strategy: Optional grounding-strategy name. When
                       omitted the service applies the DI-injected
                       default.
        metadata:      Opaque, propagated.
    """

    query: str
    policy: RetrievalPolicy | None = None
    budget: BudgetConstraint | None = None
    strategies: tuple[str, ...] | None = None
    reranker: str | None = None
    grounding_strategy: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class AssembledContext:
    """Populated success payload of one assembly call.

    Carries the full audit-grade lineage chain: which candidates came
    out of retrieval, which made it past the reranker, which made it
    past the budget, with citation indices and grounding fragments
    aligned 1:1.

    Attributes:
        query:                Original query text.
        retrieval_candidates: Candidate set produced by the retrieval
                              runtime BEFORE budgeting and grounding
                              (post-reranker order).
        budgeting:            The budgeting decisions.
        citation_index:       Citations for the included candidates.
        grounding:            Grounding fragments — one per citation.
        reranker_name:        Name of the reranker that ran.
        grounding_strategy:   Name of the grounding strategy that ran.
        metadata:             Opaque, propagated.
    """

    query: str
    retrieval_candidates: RetrievalCandidateSet
    budgeting: BudgetingResult
    citation_index: CitationIndex
    grounding: GroundingResult
    reranker_name: str
    grounding_strategy: str
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    @property
    def fragments(self):
        return self.grounding.fragments

    @property
    def citation_count(self) -> int:
        return len(self.citation_index)

    @property
    def fragment_count(self) -> int:
        return len(self.grounding)


__all__ = ["AssemblyRequest", "AssembledContext"]
