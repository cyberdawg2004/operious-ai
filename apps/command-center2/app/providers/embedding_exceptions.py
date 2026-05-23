"""Embedding provider exception hierarchy.

Same architectural discipline as `app/providers/exceptions.py`:
class-level `retryable` flags drive the embedding gateway's retry
policy. Vendor SDK exceptions are mapped onto this hierarchy inside
the concrete provider; downstream code never inspects vendor types
or message strings.
"""

from __future__ import annotations


class EmbeddingProviderError(Exception):
    """Base class for every embedding-provider failure."""

    retryable: bool = False

    def __init__(self, message: str = "", *, provider: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider


class EmbeddingAuthenticationError(EmbeddingProviderError):
    """Invalid API key / forbidden. Terminal."""
    retryable = False


class EmbeddingBadRequestError(EmbeddingProviderError):
    """Malformed request, validation failure, unsupported parameter. Terminal."""
    retryable = False


class EmbeddingNotFoundError(EmbeddingProviderError):
    """Model / resource missing. Terminal."""
    retryable = False


class EmbeddingRateLimitError(EmbeddingProviderError):
    """Rate-limited by the vendor. Retry with backoff."""
    retryable = True


class EmbeddingUnavailableError(EmbeddingProviderError):
    """Transient network / 5xx failure. Retry with backoff."""
    retryable = True


class EmbeddingTimeoutError(EmbeddingProviderError):
    """Per-attempt timeout exceeded. Retry with backoff."""
    retryable = True


class EmbeddingResponseError(EmbeddingProviderError):
    """Provider returned a malformed / unparsable response. Terminal."""
    retryable = False


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
