"""Translation provider selection shared by web and worker composition."""

from __future__ import annotations

from app.boundary.translation.adapters import (
    BaseTranslationProvider,
    IdentityTranslationProvider,
)


def build_translation_provider(
    *,
    provider_name: str,
    api_key: str | None,
    model: str | None,
    base_url: str,
    anthropic_version: str,
    timeout_seconds: float = 15.0,
) -> BaseTranslationProvider:
    """Select the translation provider from explicit runtime configuration."""

    if provider_name.casefold() == "anthropic" and (api_key or "").strip():
        from app.boundary.translation.adapters.anthropic import (
            AnthropicTranslationProvider,
        )

        return AnthropicTranslationProvider(
            api_key=api_key or "",
            model=model or "",
            base_url=base_url,
            anthropic_version=anthropic_version,
            timeout_seconds=timeout_seconds,
        )
    return IdentityTranslationProvider()


__all__ = ["build_translation_provider"]
