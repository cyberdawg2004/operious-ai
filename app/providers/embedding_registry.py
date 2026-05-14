"""Embedding provider registry.

Same architecture as the AI provider registry: explicit, opt-in,
constructed once at startup, treated as read-only afterwards.
Reviewers know which embedding providers the process is willing to
use by reading one short function in `app/dependencies/memory.py`.
"""

from __future__ import annotations

from app.providers.embedding_base import BaseEmbeddingProvider
from app.providers.embedding_exceptions import EmbeddingProviderError


class EmbeddingProviderNotRegisteredError(EmbeddingProviderError):
    """Requested embedding provider is not present in the registry."""
    retryable = False


class EmbeddingProviderAlreadyRegisteredError(EmbeddingProviderError):
    """A provider with this name was already registered."""
    retryable = False


class EmbeddingProviderRegistry:
    """Process-wide, name-keyed map of embedding providers."""

    __slots__ = ("_providers",)

    def __init__(self) -> None:
        self._providers: dict[str, BaseEmbeddingProvider] = {}

    def register(self, provider: BaseEmbeddingProvider) -> None:
        name = provider.name
        if name in self._providers:
            raise EmbeddingProviderAlreadyRegisteredError(name)
        self._providers[name] = provider

    def resolve(self, name: str) -> BaseEmbeddingProvider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise EmbeddingProviderNotRegisteredError(name) from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers.keys()))

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._providers

    def __len__(self) -> int:
        return len(self._providers)

    async def aclose(self) -> None:
        """Close every registered provider in a best-effort sweep."""
        for provider in self._providers.values():
            await provider.aclose()


__all__ = [
    "EmbeddingProviderRegistry",
    "EmbeddingProviderNotRegisteredError",
    "EmbeddingProviderAlreadyRegisteredError",
]
