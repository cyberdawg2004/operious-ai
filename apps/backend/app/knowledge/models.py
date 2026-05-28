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
    index: int
    chunk_id: KnowledgeChunkId
    vector_id: KnowledgeVectorId
    document_id: TenantKnowledgeDocumentId
    document_version: int
    content_hash: str
    ordinal: int
    score: float
    title: str
    estimated_tokens: int
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class KnowledgeRetrievalItem:
    chunk_id: KnowledgeChunkId
    vector_id: KnowledgeVectorId
    document_id: TenantKnowledgeDocumentId
    document_version: int
    content_hash: str
    ordinal: int
    score: float
    content: str
    title: str
    estimated_tokens: int
    citation_index: int
    document_status: str | None = None
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


@dataclass(frozen=True, slots=True)
class KnowledgeIngestionResult:
    tenant_id: str
    document_id: TenantKnowledgeDocumentId
    document_version: int
    chunk_count: int
    vector_count: int
    vector_index_name: str
    indexed_at: datetime


__all__ = [
    "KnowledgeBudgetDecision",
    "KnowledgeBudgetDecisionReason",
    "KnowledgeCitation",
    "KnowledgeIngestionResult",
    "KnowledgeRetrievalItem",
    "KnowledgeRetrievalResult",
]
