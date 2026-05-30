"""Tenant knowledge ingestion and retrieval substrate."""

from app.knowledge.chunking import DeterministicKnowledgeChunker, KnowledgeChunk
from app.knowledge.embeddings import (
    DeterministicHashEmbeddingProvider,
    KnowledgeEmbeddingProvider,
)
from app.knowledge.exceptions import (
    KnowledgeDocumentNotFoundError,
    KnowledgeDocumentNotIndexableError,
    KnowledgeError,
    KnowledgePersistenceError,
    KnowledgeProviderError,
    KnowledgeRetrievalError,
)
from app.knowledge.identity import (
    KnowledgeChunkId,
    KnowledgeVectorId,
    as_chunk_id,
    as_document_id,
    as_vector_id,
    derive_chunk_id,
    derive_vector_id,
)
from app.knowledge.models import (
    KnowledgeBudgetDecision,
    KnowledgeBudgetDecisionReason,
    KnowledgeCitation,
    KnowledgeIngestionResult,
    KnowledgeRetrievalItem,
    KnowledgeRetrievalResult,
)
from app.knowledge.runtime import KnowledgeRuntime

__all__ = [
    "DeterministicHashEmbeddingProvider",
    "DeterministicKnowledgeChunker",
    "KnowledgeBudgetDecision",
    "KnowledgeBudgetDecisionReason",
    "KnowledgeChunk",
    "KnowledgeChunkId",
    "KnowledgeCitation",
    "KnowledgeDocumentNotFoundError",
    "KnowledgeDocumentNotIndexableError",
    "KnowledgeEmbeddingProvider",
    "KnowledgeError",
    "KnowledgeIngestionResult",
    "KnowledgePersistenceError",
    "KnowledgeProviderError",
    "KnowledgeRetrievalError",
    "KnowledgeRetrievalItem",
    "KnowledgeRetrievalResult",
    "KnowledgeRuntime",
    "KnowledgeVectorId",
    "as_chunk_id",
    "as_document_id",
    "as_vector_id",
    "derive_chunk_id",
    "derive_vector_id",
]
