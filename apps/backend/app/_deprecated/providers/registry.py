"""Provider registry.

A tiny, explicit mapping of `name → BaseAIProvider`. Construction is
the caller's responsibility — usually the dependency layer
(`app.dependencies.providers`) which reads `Settings` and registers
whatever providers it has credentials for.

Why an explicit registry instead of import-time auto-registration:

* New providers must opt in by being constructed; CI and offline
  development environments run with no API keys and simply produce a
  registry with no entries.
* The dispatch path through the gateway is a single dict lookup, with
  a clear failure mode (`KeyError` → typed exception) — no plugin
  discovery, no entrypoint scans, no surprise side effects.
"""

from __future__ import annotations

from app._deprecated.providers.base import BaseAIProvider
from app._deprecated.providers.exceptions import AIProviderError


class ProviderNotRegisteredError(AIProviderError):
    """Requested provider is not present in the registry."""
    retryable = False


class ProviderAlreadyRegisteredError(AIProviderError):
    """A provider with this name was already registered."""
    retryable = False


class ProviderRegistry:
    """Process-wide, name-keyed map of providers.

    Not thread-safe and intentionally so — the registry is constructed
    once at startup, then read-only for the rest of the process
    lifetime. Mutating it from request handlers is a bug.
    """

    __slots__ = ("_providers",)

    def __init__(self) -> None:
        self._providers: dict[str, BaseAIProvider] = {}

    # ─── Mutation (startup only) ──────────────────────────────────────

    def register(self, provider: BaseAIProvider) -> None:
        """Register a provider under its declared name."""
        name = provider.name
        if name in self._providers:
            raise ProviderAlreadyRegisteredError(name)
        self._providers[name] = provider

    # ─── Read access ──────────────────────────────────────────────────

    def resolve(self, name: str) -> BaseAIProvider:
        """Return the named provider or raise `ProviderNotRegisteredError`."""
        try:
            return self._providers[name]
        except KeyError as exc:
            raise ProviderNotRegisteredError(name) from exc

    def names(self) -> tuple[str, ...]:
        """Sorted tuple of registered provider names."""
        return tuple(sorted(self._providers.keys()))

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._providers

    def __len__(self) -> int:
        return len(self._providers)

    # ─── Lifecycle ────────────────────────────────────────────────────

    async def aclose(self) -> None:
        """Close every registered provider in a best-effort sweep."""
        for provider in self._providers.values():
            await provider.aclose()


__all__ = [
    "ProviderRegistry",
    "ProviderNotRegisteredError",
    "ProviderAlreadyRegisteredError",
]
