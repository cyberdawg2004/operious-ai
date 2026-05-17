"""Vector provider registry.

Identical architecture to the embedding / AI provider registries:
explicit registration, opt-in at startup, treated as read-only
afterwards. Reviewers know which vector backends the process is
willing to use by reading one short function in
`app/dependencies/memory.py`.
"""

from __future__ import annotations

from app._deprecated.providers.vector_base import BaseVectorProvider
from app._deprecated.providers.vector_exceptions import VectorProviderError


class VectorProviderNotRegisteredError(VectorProviderError):
    """Requested vector provider is not present in the registry."""
    retryable = False


class VectorProviderAlreadyRegisteredError(VectorProviderError):
    """A provider with this name was already registered."""
    retryable = False


class VectorProviderRegistry:
    """Process-wide, name-keyed map of vector providers."""

    __slots__ = ("_providers",)

    def __init__(self) -> None:
        self._providers: dict[str, BaseVectorProvider] = {}

    def register(self, provider: BaseVectorProvider) -> None:
        name = provider.name
        if name in self._providers:
            raise VectorProviderAlreadyRegisteredError(name)
        self._providers[name] = provider

    def resolve(self, name: str) -> BaseVectorProvider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise VectorProviderNotRegisteredError(name) from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers.keys()))

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._providers

    def __len__(self) -> int:
        return len(self._providers)

    async def aclose(self) -> None:
        for provider in self._providers.values():
            await provider.aclose()


__all__ = [
    "VectorProviderRegistry",
    "VectorProviderNotRegisteredError",
    "VectorProviderAlreadyRegisteredError",
]
