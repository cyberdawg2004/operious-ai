from __future__ import annotations

import pytest

from app.boundary.translation.adapters.stub import (
    DeterministicStubTranslationProvider,
)
from app.boundary.translation.adapters.base import TranslationProviderRequest
from app.boundary.translation.models.payload import TranslationPayload


@pytest.mark.asyncio
async def test_cross_language_produces_prefix() -> None:
    provider = DeterministicStubTranslationProvider()

    response = await provider.translate(
        TranslationProviderRequest(
            source=TranslationPayload(text="hello", language="ar"),
            target_language="en",
        )
    )

    assert response.translated.text == "[ar→en] hello"
    assert response.translated.language == "en"
    assert response.provider_name == "deterministic_stub"


@pytest.mark.asyncio
async def test_same_language_returns_verbatim() -> None:
    provider = DeterministicStubTranslationProvider()

    response = await provider.translate(
        TranslationProviderRequest(
            source=TranslationPayload(text="hello", language="en"),
            target_language="en",
        )
    )

    assert response.translated.text == "hello"
    assert response.translated.language == "en"
