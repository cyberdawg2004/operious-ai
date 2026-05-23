"""Facade re-export of the embedding-provider exception hierarchy.

Same rationale as `app/embeddings/models.py`: canonical definitions
live in `app/providers/embedding_exceptions.py`; this module re-exports
them so consumers of the embedding subsystem have a stable import
path that does not reach into the provider package.
"""

from app.providers.embedding_exceptions import (
    EmbeddingAuthenticationError,
    EmbeddingBadRequestError,
    EmbeddingNotFoundError,
    EmbeddingProviderError,
    EmbeddingRateLimitError,
    EmbeddingResponseError,
    EmbeddingTimeoutError,
    EmbeddingUnavailableError,
)

__all__ = [
    "EmbeddingProviderError",
    "EmbeddingAuthenticationError",
    "EmbeddingBadRequestError",
    "EmbeddingNotFoundError",
    "EmbeddingRateLimitError",
    "EmbeddingUnavailableError",
    "EmbeddingTimeoutError",
    "EmbeddingResponseError",
]
