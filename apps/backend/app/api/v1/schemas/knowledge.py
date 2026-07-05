"""Transport contracts for tenant knowledge endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.knowledge.models import (
    KnowledgeAnalysisResult,
    KnowledgeBudgetDecision,
    KnowledgeCitation,
    KnowledgeIngestionResult,
    KnowledgeRetrievalItem,
    KnowledgeRetrievalResult,
)


class KnowledgeIngestionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    document_id: str
    document_version: int
    chunk_count: int
    vector_count: int
    vector_index_name: str
    indexed_at: str

    @classmethod
    def from_result(
        cls,
        result: KnowledgeIngestionResult,
    ) -> "KnowledgeIngestionResponse":
        return cls(
            tenant_id=result.tenant_id,
            document_id=str(result.document_id),
            document_version=result.document_version,
            chunk_count=result.chunk_count,
            vector_count=result.vector_count,
            vector_index_name=result.vector_index_name,
            indexed_at=result.indexed_at.isoformat(),
        )


class KnowledgeSearchRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str = Field(min_length=1)
    top_k: int = Field(default=8, ge=0, le=50)
    max_tokens: int | None = Field(default=None, ge=0)
    max_chunks_per_document: int | None = Field(default=None, ge=0)
    min_score: float | None = None


class KnowledgeCitationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int
    chunk_id: str
    vector_id: str
    document_id: str
    document_version: int
    ordinal: int
    char_start: int
    char_end: int
    score: float
    title: str
    estimated_tokens: int
    metadata: dict[str, Any]

    @classmethod
    def from_citation(
        cls,
        citation: KnowledgeCitation,
    ) -> "KnowledgeCitationResponse":
        return cls(
            index=citation.index,
            chunk_id=str(citation.chunk_id),
            vector_id=str(citation.vector_id),
            document_id=str(citation.document_id),
            document_version=citation.document_version,
            ordinal=citation.ordinal,
            char_start=citation.char_start,
            char_end=citation.char_end,
            score=citation.score,
            title=citation.title,
            estimated_tokens=citation.estimated_tokens,
            metadata=dict(citation.metadata),
        )


class KnowledgeSearchItemResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str
    vector_id: str
    document_id: str
    document_version: int
    ordinal: int
    char_start: int
    char_end: int
    score: float
    content: str
    title: str
    estimated_tokens: int
    citation_index: int
    metadata: dict[str, Any]

    @classmethod
    def from_item(
        cls,
        item: KnowledgeRetrievalItem,
    ) -> "KnowledgeSearchItemResponse":
        return cls(
            chunk_id=str(item.chunk_id),
            vector_id=str(item.vector_id),
            document_id=str(item.document_id),
            document_version=item.document_version,
            ordinal=item.ordinal,
            char_start=item.char_start,
            char_end=item.char_end,
            score=item.score,
            content=item.content,
            title=item.title,
            estimated_tokens=item.estimated_tokens,
            citation_index=item.citation_index,
            metadata=dict(item.metadata),
        )


class KnowledgeBudgetDecisionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str
    document_id: str
    score: float
    estimated_tokens: int
    reason: str
    included: bool

    @classmethod
    def from_decision(
        cls,
        decision: KnowledgeBudgetDecision,
    ) -> "KnowledgeBudgetDecisionResponse":
        return cls(
            chunk_id=str(decision.chunk_id),
            document_id=str(decision.document_id),
            score=decision.score,
            estimated_tokens=decision.estimated_tokens,
            reason=decision.reason.value,
            included=decision.included,
        )


class KnowledgeSearchResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    query: str
    items: list[KnowledgeSearchItemResponse]
    citations: list[KnowledgeCitationResponse]
    budget_decisions: list[KnowledgeBudgetDecisionResponse]
    total_tokens: int
    vector_index_name: str

    @classmethod
    def from_result(
        cls,
        result: KnowledgeRetrievalResult,
    ) -> "KnowledgeSearchResponse":
        return cls(
            tenant_id=result.tenant_id,
            query=result.query,
            items=[
                KnowledgeSearchItemResponse.from_item(item)
                for item in result.items
            ],
            citations=[
                KnowledgeCitationResponse.from_citation(citation)
                for citation in result.citations
            ],
            budget_decisions=[
                KnowledgeBudgetDecisionResponse.from_decision(decision)
                for decision in result.budget_decisions
            ],
            total_tokens=result.total_tokens,
            vector_index_name=result.vector_index_name,
        )


class KnowledgeConflictResponse(BaseModel):
    """One detected contradiction between two KB documents."""
    model_config = ConfigDict(frozen=True)

    doc_a_id: str
    doc_a_title: str
    doc_b_id: str
    doc_b_title: str
    excerpt_a: str
    excerpt_b: str
    contradiction_type: str
    confidence: float


class KnowledgeAnalyzeRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_types: list[str] = Field(
        default_factory=list,
        description="Filter to specific document types (sop, policy). Empty = all.",
    )


class KnowledgeAnalyzeResponse(BaseModel):
    """Full KB analysis report returned to the manager."""
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    documents_analyzed: int
    contradictions_found: int
    conflicts: list[KnowledgeConflictResponse]
    # Existing quarantined docs with contradiction_metadata already on file
    quarantined_with_detail: list[dict[str, Any]]
    # Whether the trainer (gap/recommendation) task was enqueued
    trainer_enqueued: bool
    analyzed_at: str

    @classmethod
    def from_result(cls, result: "KnowledgeAnalysisResult") -> "KnowledgeAnalyzeResponse":
        return cls(
            tenant_id=result.tenant_id,
            documents_analyzed=result.documents_analyzed,
            contradictions_found=result.contradictions_found,
            conflicts=[
                KnowledgeConflictResponse(
                    doc_a_id=c["doc_a_id"],
                    doc_a_title=c["doc_a_title"],
                    doc_b_id=c["doc_b_id"],
                    doc_b_title=c["doc_b_title"],
                    excerpt_a=c["excerpt_a"],
                    excerpt_b=c["excerpt_b"],
                    contradiction_type=c["contradiction_type"],
                    confidence=c["confidence"],
                )
                for c in result.conflicts
            ],
            quarantined_with_detail=result.quarantined_with_detail,
            trainer_enqueued=result.trainer_enqueued,
            analyzed_at=result.analyzed_at.isoformat(),
        )


__all__ = [
    "KnowledgeAnalyzeRequest",
    "KnowledgeAnalyzeResponse",
    "KnowledgeBudgetDecisionResponse",
    "KnowledgeCitationResponse",
    "KnowledgeConflictResponse",
    "KnowledgeIngestionResponse",
    "KnowledgeSearchItemResponse",
    "KnowledgeSearchRequest",
    "KnowledgeSearchResponse",
]
