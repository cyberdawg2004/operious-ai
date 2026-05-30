"""Anthropic translation provider.

Calls the Anthropic Messages API directly via httpx. This adapter does
not import from the cognition substrate.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, cast

from app.boundary.translation.adapters.base import (
    BaseTranslationProvider,
    TranslationProviderRequest,
    TranslationProviderResponse,
)
from app.boundary.translation.enums import TranslationProviderKind
from app.boundary.translation.models.payload import TranslationPayload
from app.core.http import get_shared_http_client

logger = logging.getLogger(__name__)

_MAX_OUTPUT_TOKENS = 2048
_SYSTEM_PROMPT = (
    "You are a professional translator. "
    "Translate the following text accurately. "
    "Return only the translated text. "
    "No explanation. No quotes. No commentary. "
    "Preserve formatting and tone."
)


class AnthropicTranslationProvider(BaseTranslationProvider):
    """Translation provider backed by Anthropic Claude.

    Fail-open: any provider error returns the source text unchanged.
    """

    __slots__ = (
        "_anthropic_version",
        "_api_key",
        "_base_url",
        "_model",
        "_name",
        "_timeout_seconds",
    )

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        anthropic_version: str,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._anthropic_version = anthropic_version
        self._timeout_seconds = timeout_seconds
        self._name = "anthropic"

    @property
    def name(self) -> str:
        return self._name

    @property
    def kind(self) -> TranslationProviderKind:
        return TranslationProviderKind.EXTERNAL

    async def translate(
        self,
        request: TranslationProviderRequest,
    ) -> TranslationProviderResponse:
        """Translate source text, returning source text on any failure."""

        source_language = request.source.language
        target_language = request.target_language

        if source_language == target_language:
            return TranslationProviderResponse(
                translated=TranslationPayload(
                    text=request.source.text,
                    language=target_language,
                    attributes=request.source.attributes,
                ),
                provider_name=self._name,
            )

        if not self._api_key.strip() or not self._model.strip():
            logger.warning(
                "anthropic_translation_not_configured",
                extra={
                    "source_language": source_language,
                    "target_language": target_language,
                },
            )
            return self._identity_response(request)

        try:
            response = await get_shared_http_client().post(
                f"{self._base_url}/v1/messages",
                json={
                    "model": self._model,
                    "max_tokens": _MAX_OUTPUT_TOKENS,
                    "system": _SYSTEM_PROMPT,
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                "Translate from "
                                f"{source_language} to {target_language}:\n\n"
                                f"{request.source.text}"
                            ),
                        }
                    ],
                },
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": self._anthropic_version,
                    "content-type": "application/json",
                },
                timeout=self._timeout_seconds,
            )

            if response.status_code != 200:
                logger.warning(
                    "anthropic_translation_http_error",
                    extra={
                        "status_code": response.status_code,
                        "source_language": source_language,
                        "target_language": target_language,
                    },
                )
                return self._identity_response(request)

            data = cast(Mapping[str, Any], response.json())
            translated_text = _extract_translated_text(
                data,
                fallback=request.source.text,
            )
            return TranslationProviderResponse(
                translated=TranslationPayload(
                    text=translated_text,
                    language=target_language,
                    attributes=request.source.attributes,
                ),
                provider_name=self._name,
            )
        except Exception as exc:
            logger.warning(
                "anthropic_translation_failed",
                extra={
                    "error_type": exc.__class__.__name__,
                    "source_language": source_language,
                    "target_language": target_language,
                },
            )
            return self._identity_response(request)

    def _identity_response(
        self,
        request: TranslationProviderRequest,
    ) -> TranslationProviderResponse:
        """Fail-open fallback: return source text unchanged."""

        return TranslationProviderResponse(
            translated=TranslationPayload(
                text=request.source.text,
                language=request.target_language,
                attributes=request.source.attributes,
            ),
            provider_name=f"{self._name}:fallback",
        )


def _extract_translated_text(
    data: Mapping[str, Any],
    *,
    fallback: str,
) -> str:
    content_value = data.get("content")
    if not isinstance(content_value, list) or not content_value:
        return fallback
    content = cast(list[object], content_value)
    first_block = content[0]
    if not isinstance(first_block, Mapping):
        return fallback
    block = cast(Mapping[str, Any], first_block)
    text = block.get("text")
    if not isinstance(text, str):
        return fallback
    stripped = text.strip()
    return stripped if stripped else fallback


__all__ = ["AnthropicTranslationProvider"]
