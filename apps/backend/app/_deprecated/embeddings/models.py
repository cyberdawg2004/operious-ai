"""Facade re-export of vendor-neutral embedding types.

The canonical definitions live with the provider abstraction
(`app/providers/embedding_models.py`) because they are the *provider
contract*. This module re-exports them so consumers of the embedding
*subsystem* (gateway, ingestion / retrieval services, orchestration
tasks) have a clean `from app._deprecated.embeddings.models import …` import path
that does not reach into the provider package.
"""

from app._deprecated.providers.embedding_models import (
    EmbeddingProviderCapability,
    EmbeddingProviderInfo,
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingUsage,
)

__all__ = [
    "EmbeddingRequest",
    "EmbeddingResponse",
    "EmbeddingUsage",
    "EmbeddingProviderCapability",
    "EmbeddingProviderInfo",
]
