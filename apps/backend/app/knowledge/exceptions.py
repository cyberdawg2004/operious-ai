"""Knowledge runtime exception hierarchy."""

from __future__ import annotations


class KnowledgeError(RuntimeError):
    """Base class for tenant knowledge runtime failures."""


class KnowledgePersistenceError(KnowledgeError):
    """Raised when tenant knowledge persistence refuses an operation."""


class KnowledgeRetrievalError(KnowledgeError):
    """Raised when tenant knowledge retrieval cannot complete safely."""


class KnowledgeProviderError(KnowledgeRetrievalError):
    """Raised when a knowledge provider fails during retrieval."""


class KnowledgeDocumentNotFoundError(KnowledgeError):
    """Raised when the requested tenant knowledge document is missing."""


class KnowledgeDocumentNotIndexableError(KnowledgeError):
    """Raised when a document cannot participate in the RAG corpus."""


__all__ = [
    "KnowledgeDocumentNotFoundError",
    "KnowledgeDocumentNotIndexableError",
    "KnowledgeError",
    "KnowledgePersistenceError",
    "KnowledgeProviderError",
    "KnowledgeRetrievalError",
]
