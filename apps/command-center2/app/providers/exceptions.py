"""Provider exception hierarchy.

Every concrete provider catches its vendor SDK exceptions and re-raises
one of these typed errors. The `retryable` class attribute is the
contract the gateway's retry policy reads against — it does NOT inspect
messages, status codes, or vendor types. That asymmetry is what keeps
retry behaviour stable as we add providers.
"""

from __future__ import annotations


class AIProviderError(Exception):
    """Base class for every provider-level failure.

    Subclasses set `retryable` to indicate whether the gateway should
    attempt another invocation. The default is `False` — adding a new
    provider error class must consciously opt in to retry semantics.
    """

    retryable: bool = False

    def __init__(self, message: str = "", *, provider: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider


class ProviderAuthenticationError(AIProviderError):
    """Invalid API key / forbidden. Terminal — do not retry."""
    retryable = False


class ProviderBadRequestError(AIProviderError):
    """Malformed request, validation failure, unsupported parameter. Terminal."""
    retryable = False


class ProviderNotFoundError(AIProviderError):
    """Model / resource missing. Terminal."""
    retryable = False


class ProviderRateLimitError(AIProviderError):
    """Rate-limited by the vendor. Retry with backoff."""
    retryable = True


class ProviderUnavailableError(AIProviderError):
    """Transient network / 5xx failure. Retry with backoff."""
    retryable = True


class ProviderTimeoutError(AIProviderError):
    """Per-attempt timeout exceeded. Retry with backoff."""
    retryable = True


class ProviderResponseError(AIProviderError):
    """Provider returned a malformed / unparsable response. Terminal."""
    retryable = False


__all__ = [
    "AIProviderError",
    "ProviderAuthenticationError",
    "ProviderBadRequestError",
    "ProviderNotFoundError",
    "ProviderRateLimitError",
    "ProviderUnavailableError",
    "ProviderTimeoutError",
    "ProviderResponseError",
]
