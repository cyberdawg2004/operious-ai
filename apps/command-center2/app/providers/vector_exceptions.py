"""Vector-provider exception hierarchy.

Same architectural discipline as the embedding / AI provider
hierarchies: class-level `retryable` flags so any future retry layer
over vector operations works by type rather than by string matching.

Sprint G does NOT add retries around vector operations — those land
in a later sprint when failure modes are better understood. The
hierarchy is in place so retries can be added without API changes.
"""

from __future__ import annotations


class VectorProviderError(Exception):
    """Base class for every vector-provider failure."""

    retryable: bool = False

    def __init__(self, message: str = "", *, provider: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider


class VectorIndexNotFoundError(VectorProviderError):
    """Operation referenced an index that does not exist."""
    retryable = False


class VectorIndexDimensionMismatchError(VectorProviderError):
    """Upsert / query vector dimension does not match the index."""
    retryable = False


class VectorProviderUnavailableError(VectorProviderError):
    """Transient backend failure. (Reserved for remote providers.)"""
    retryable = True


__all__ = [
    "VectorProviderError",
    "VectorIndexNotFoundError",
    "VectorIndexDimensionMismatchError",
    "VectorProviderUnavailableError",
]
