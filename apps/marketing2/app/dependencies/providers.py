"""AI provider / gateway / service dependency providers.

Builds the process-wide provider registry from `Settings`, composes the
`AIGateway` over it, and exposes both as FastAPI dependencies along
with the `AIService`.

Lifecycle:

* The registry and gateway are constructed lazily on first use and
  cached for the process lifetime (`lru_cache`).
* `close_ai_providers()` disposes every registered provider on
  application shutdown; `main.py`'s lifespan calls it.

Adding a new provider:

1. Implement it under `app/providers/<name>_provider.py`.
2. Add the env vars to `Settings`.
3. Extend `_build_registry()` here with a conditional registration
   keyed on the credentials being present.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends

from app.ai.gateway import AIGateway
from app.ai.retry import RetryPolicy
from app.core.config import Settings, get_settings
from app.providers.openai_provider import OpenAIProvider
from app.providers.registry import ProviderRegistry
from app.services.ai_service import AIService


@lru_cache(maxsize=1)
def _build_registry() -> ProviderRegistry:
    settings = get_settings()
    registry = ProviderRegistry()

    # OpenAI: register only when an API key is configured. A missing
    # key is a normal state in CI and offline development — the
    # registry simply has no entry for "openai".
    if settings.OPENAI_API_KEY:
        registry.register(
            OpenAIProvider(
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL,
                default_timeout=settings.AI_TIMEOUT_SECONDS,
                default_model=settings.OPENAI_DEFAULT_MODEL,
            )
        )

    return registry


def get_provider_registry() -> ProviderRegistry:
    """Return the process-wide provider registry."""
    return _build_registry()


@lru_cache(maxsize=1)
def _build_gateway() -> AIGateway:
    settings = get_settings()
    return AIGateway(
        registry=_build_registry(),
        retry_policy=RetryPolicy(
            max_attempts=settings.AI_MAX_ATTEMPTS,
            backoff_base=settings.AI_RETRY_BACKOFF_BASE,
            backoff_max=settings.AI_RETRY_BACKOFF_MAX,
        ),
        default_provider=settings.AI_DEFAULT_PROVIDER,
        per_attempt_timeout_s=settings.AI_TIMEOUT_SECONDS,
    )


def get_ai_gateway() -> AIGateway:
    """Return the process-wide AI gateway."""
    return _build_gateway()


def get_ai_service(
    gateway: AIGateway = Depends(get_ai_gateway),
    settings: Settings = Depends(get_settings),
) -> AIService:
    """FastAPI dependency: construct `AIService` per request."""
    return AIService(
        gateway=gateway,
        default_model=settings.OPENAI_DEFAULT_MODEL,
    )


async def close_ai_providers() -> None:
    """Dispose the process-wide registry on shutdown.

    Safe to call even if the registry was never built — we check the
    `lru_cache` state to avoid construction-on-shutdown surprises.
    """
    if _build_registry.cache_info().currsize == 0:
        return
    registry = _build_registry()
    await registry.aclose()


__all__ = [
    "get_provider_registry",
    "get_ai_gateway",
    "get_ai_service",
    "close_ai_providers",
]
