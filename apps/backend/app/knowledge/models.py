"""Knowledge runtime result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping

from app.knowledge.identity import KnowledgeChunkId, KnowledgeVectorId
from app.tenant.identity import TenantKnowledgeDocumentId


def _empty_metadata() -> dict[str, Any]:
    return {}


class KnowledgeBudgetDecisionReason(StrEnum):
    INCLUDED = "included"
    BELOW_MIN_SCORE = "below_min_score"
    EXCEEDED_CHUNK_BUDGET = "exceeded_chunk_budget"
    EXCEEDED_TOKEN_BUDGET = "exceeded_token_budget"
    EXCEEDED_PER_DOCUMENT_CAP = "exceeded_per_document_cap"


@dataclass(frozen=True, slots=True)
class KnowledgeCitation:
    """Chunk citation with document-relative span provenance.

    ``char_start`` / ``char_end`` index into ``document.content.strip()``.
    The invariant is:
    ``document.content.strip()[char_start:char_end] == chunk.content``.
    """

    index: int
    chunk_id: KnowledgeChunkId
    vector_id: KnowledgeVectorId
    document_id: TenantKnowledgeDocumentId
    document_version: int
    content_hash: str
    ordinal: int
    char_start: int
    char_end: int
    score: float
    title: str
    estimated_tokens: int
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class KnowledgeRetrievalItem:
    """Retrieved chunk with document-relative span provenance.

    ``char_start`` / ``char_end`` index into ``document.content.strip()``.
    The invariant is:
    ``document.content.strip()[char_start:char_end] == content``.
    """

    chunk_id: KnowledgeChunkId
    vector_id: KnowledgeVectorId
    document_id: TenantKnowledgeDocumentId
    document_version: int
    content_hash: str
    ordinal: int
    char_start: int
    char_end: int
    score: float
    content: str
    title: str
    estimated_tokens: int
    citation_index: int
    document_status: str | None = None
    document_review_status: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class KnowledgeBudgetDecision:
    chunk_id: KnowledgeChunkId
    document_id: TenantKnowledgeDocumentId
    score: float
    estimated_tokens: int
    reason: KnowledgeBudgetDecisionReason

    @property
    def included(self) -> bool:
        return self.reason is KnowledgeBudgetDecisionReason.INCLUDED


@dataclass(frozen=True, slots=True)
class KnowledgeRetrievalResult:
    tenant_id: str
    query: str
    items: tuple[KnowledgeRetrievalItem, ...]
    citations: tuple[KnowledgeCitation, ...]
    budget_decisions: tuple[KnowledgeBudgetDecision, ...]
    total_tokens: int
    vector_index_name: str


class ContradictionCheckStatus(StrEnum):
    """Tri-state outcome of the MVP-4 SOP contradiction check.

    These three states are INTENTIONALLY distinguishable — "unchecked" must
    never be indistinguishable from "clean".

    CHECKED_CLEAN: agent ran, no contradiction found → document admitted.
    CHECKED_CONTRADICTION: agent ran, contradiction found → document quarantined.
    UNCHECKED_AGENT_UNAVAILABLE: agent could not run (error/timeout/no policy)
        → document quarantined for human review. "The check did not run" is
        treated as a known-unknown, NOT as a clean result. Human must verify
        before the document is admitted to the active KB.
    NOT_APPLICABLE: document type is not subject to contradiction checking
        (FAQ, TEMPLATE, PRODUCT_GUIDE, etc.), or no agent is wired.
    """

    CHECKED_CLEAN = "checked_clean"
    CHECKED_CONTRADICTION = "checked_contradiction"
    UNCHECKED_AGENT_UNAVAILABLE = "unchecked_agent_unavailable"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class KnowledgeIngestionResult:
    tenant_id: str
    document_id: TenantKnowledgeDocumentId
    document_version: int
    chunk_count: int
    vector_count: int
    vector_index_name: str
    indexed_at: datetime
    # MVP-4: tri-state contradiction check outcome.
    # NOT_APPLICABLE when no agent is wired or document type is exempt.
    # UNCHECKED_AGENT_UNAVAILABLE when agent failed — document is quarantined,
    # chunk_count=0, vector_count=0. Requires human review before admission.
    contradiction_check_status: ContradictionCheckStatus = (
        ContradictionCheckStatus.NOT_APPLICABLE
    )
    contradiction_metadata: dict[str, object] | None = None


__all__ = [
    "ContradictionCheckStatus",
    "KnowledgeBudgetDecision",
    "KnowledgeBudgetDecisionReason",
    "KnowledgeCitation",
    "KnowledgeIngestionResult",
    "KnowledgeRetrievalItem",
    "KnowledgeRetrievalResult",
]
