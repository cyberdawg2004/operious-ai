"""Deterministic stub translation provider."""

from __future__ import annotations

from app.boundary.translation.adapters.base import (
    BaseTranslationProvider,
    TranslationProviderRequest,
    TranslationProviderResponse,
)
from app.boundary.translation.enums import TranslationProviderKind
from app.boundary.translation.models.payload import TranslationPayload


class DeterministicStubTranslationProvider(BaseTranslationProvider):
    """Prefix-tag cross-language translations for testability."""

    __slots__ = ("_name",)

    def __init__(self, *, name: str = "deterministic_stub") -> None:
        if not name:
            raise ValueError(
                "DeterministicStubTranslationProvider.name must be non-empty"
            )
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def kind(self) -> TranslationProviderKind:
        return TranslationProviderKind.DETERMINISTIC_STUB

    async def translate(
        self, request: TranslationProviderRequest
    ) -> TranslationProviderResponse:
        if request.source.language == request.target_language:
            text = request.source.text
        else:
            text = (
                f"[{request.source.language}→{request.target_language}] "
                f"{request.source.text}"
            )
        return TranslationProviderResponse(
            translated=TranslationPayload(
                text=text,
                language=request.target_language,
                attributes=request.source.attributes,
            ),
            provider_name=self._name,
        )
