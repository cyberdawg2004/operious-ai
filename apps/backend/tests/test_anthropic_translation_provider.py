"""Anthropic translation provider tests."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Any

import pytest

import app.boundary.translation.adapters.anthropic as anthropic_module
from app.boundary.translation.adapters.anthropic import (
    AnthropicTranslationProvider,
)
from app.boundary.translation.adapters.identity import (
    IdentityTranslationProvider,
)
from app.boundary.translation.adapters.base import (
    TranslationProviderRequest,
)
from app.boundary.translation.models.payload import TranslationPayload
from app.core.config import Settings
from app.main import _build_translation_provider


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeHTTPClient:
    def __init__(
        self,
        *,
        response: _FakeResponse | None = None,
        exc: Exception | None = None,
    ) -> None:
        self._response = response or _FakeResponse(status_code=200)
        self._exc = exc
        self.calls: list[dict[str, Any]] = []

    async def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> _FakeResponse:
        self.calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        if self._exc is not None:
            raise self._exc
        return self._response


def _provider(*, api_key: str = "secret-test-key") -> AnthropicTranslationProvider:
    return AnthropicTranslationProvider(
        api_key=api_key,
        model="claude-test",
        base_url="https://anthropic.test",
        anthropic_version="2023-06-01",
        timeout_seconds=7.0,
    )


def _request(
    *,
    text: str = "مرحبا، أحتاج مساعدة في طلبي.",
    source_language: str = "ar",
    target_language: str = "en",
) -> TranslationProviderRequest:
    return TranslationProviderRequest(
        source=TranslationPayload(
            text=text,
            language=source_language,
            attributes={"ticket_id": "ticket-1"},
        ),
        target_language=target_language,
    )


@pytest.mark.asyncio
async def test_translate_arabic_to_english_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeHTTPClient(
        response=_FakeResponse(
            status_code=200,
            payload={"content": [{"type": "text", "text": "Hello, I need help."}]},
        )
    )
    monkeypatch.setattr(
        anthropic_module,
        "get_shared_http_client",
        lambda: client,
    )

    result = await _provider().translate(_request())

    assert result.translated.text == "Hello, I need help."
    assert result.translated.language == "en"
    assert result.provider_name == "anthropic"
    assert len(client.calls) == 1
    assert client.calls[0]["headers"] == {
        "x-api-key": "secret-test-key",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }


@pytest.mark.asyncio
async def test_translate_same_language_no_api_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeHTTPClient()
    monkeypatch.setattr(
        anthropic_module,
        "get_shared_http_client",
        lambda: client,
    )

    result = await _provider().translate(
        _request(
            text="Hello",
            source_language="en",
            target_language="en",
        )
    )

    assert result.translated.text == "Hello"
    assert result.translated.language == "en"
    assert client.calls == []


@pytest.mark.asyncio
async def test_translate_http_error_returns_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeHTTPClient(response=_FakeResponse(status_code=429))
    monkeypatch.setattr(
        anthropic_module,
        "get_shared_http_client",
        lambda: client,
    )
    request = _request()

    result = await _provider().translate(request)

    assert result.translated.text == request.source.text
    assert result.translated.language == "en"
    assert result.provider_name == "anthropic:fallback"


@pytest.mark.asyncio
async def test_translate_exception_returns_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeHTTPClient(exc=ConnectionError("network unavailable"))
    monkeypatch.setattr(
        anthropic_module,
        "get_shared_http_client",
        lambda: client,
    )
    request = _request()

    result = await _provider().translate(request)

    assert result.translated.text == request.source.text
    assert result.translated.language == "en"
    assert result.provider_name == "anthropic:fallback"


@pytest.mark.asyncio
async def test_api_key_never_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    api_key = "super-secret-translation-key"
    client = _FakeHTTPClient(exc=ConnectionError(f"failed with {api_key}"))
    monkeypatch.setattr(
        anthropic_module,
        "get_shared_http_client",
        lambda: client,
    )
    caplog.set_level(
        logging.WARNING,
        logger="app.boundary.translation.adapters.anthropic",
    )

    await _provider(api_key=api_key).translate(_request())

    assert api_key not in caplog.text


def test_config_selects_anthropic_when_set() -> None:
    provider = _build_translation_provider(
        Settings(
            TRANSLATION_PROVIDER="anthropic",
            ANTHROPIC_API_KEY="secret-test-key",
        )
    )

    assert isinstance(provider, AnthropicTranslationProvider)


def test_config_falls_back_to_identity_without_key() -> None:
    provider = _build_translation_provider(
        Settings(
            TRANSLATION_PROVIDER="anthropic",
            ANTHROPIC_API_KEY="",
        )
    )

    assert isinstance(provider, IdentityTranslationProvider)


def test_no_cognition_import_in_translation_adapter() -> None:
    module_path = anthropic_module.__file__
    assert module_path is not None
    tree = ast.parse(Path(module_path).read_text(encoding="utf-8"))
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.append(node.module)

    assert all("cognition" not in module for module in imported_modules)
