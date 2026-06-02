"""Translation provider selection shared by web and worker composition."""

from __future__ import annotations

from app.boundary.translation.adapters import (
    BaseTranslationProvider,
    IdentityTranslationProvider,
)
from app.core.config import Settings


def build_translation_provider(settings: Settings) -> BaseTranslationProvider:
    """Select the translation provider from runtime configuration."""

    if (
        settings.TRANSLATION_PROVIDER.casefold() == "anthropic"
        and settings.ANTHROPIC_API_KEY.strip()
    ):
        from app.boundary.translation.adapters.anthropic import (
            AnthropicTranslationProvider,
        )

        return AnthropicTranslationProvider(
            api_key=settings.ANTHROPIC_API_KEY,
            model=settings.TRANSLATION_MODEL,
            base_url=settings.ANTHROPIC_BASE_URL,
            anthropic_version=settings.ANTHROPIC_VERSION,
            timeout_seconds=15.0,
        )
    return IdentityTranslationProvider()


__all__ = ["build_translation_provider"]
