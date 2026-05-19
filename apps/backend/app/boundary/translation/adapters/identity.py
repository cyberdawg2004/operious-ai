"""`IdentityTranslationProvider` — deterministic identity provider.

The identity provider is the boundary's pure-deterministic
fallback. It returns the source text verbatim, only changing
the language tag. This is the **only** provider safe to use in
test harnesses and replay-equivalence verification.

Real translation providers (whose outputs are nondeterministic)
must be wrapped by an external normalisation + cache layer
before being used as a runtime provider.
"""

from __future__ import annotations

from app.boundary.translation.enums import (
    TranslationProviderKind,
)
from app.boundary.translation.models.payload import (
    TranslationPayload,
)
from app.boundary.translation.adapters.base import (
    BaseTranslationProvider,
    TranslationProviderRequest,
    TranslationProviderResponse,
)


class IdentityTranslationProvider(BaseTranslationProvider):
    """Returns the source text verbatim under the target language tag."""

    __slots__ = ("_name",)

    def __init__(self, *, name: str = "identity") -> None:
        if not name:
            raise ValueError(
                "IdentityTranslationProvider.name must be non-empty"
            )
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def kind(self) -> TranslationProviderKind:
        return TranslationProviderKind.IDENTITY

    async def translate(
        self, request: TranslationProviderRequest
    ) -> TranslationProviderResponse:
        translated = TranslationPayload(
            text=request.source.text,
            language=request.target_language,
            attributes=request.source.attributes,
        )
        return TranslationProviderResponse(
            translated=translated,
            provider_name=self._name,
        )


__all__ = ["IdentityTranslationProvider"]
