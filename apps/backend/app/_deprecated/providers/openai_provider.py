"""OpenAI provider implementation.

The only file in the codebase that imports `openai`. Every vendor
exception is mapped to the platform's `AIProviderError` hierarchy;
every vendor field is normalised onto `InferenceResponse`. Downstream
code (gateway, services, future orchestration) never sees an
`openai.*` symbol.

Per-call timeouts come from the request (`InferenceRequest.timeout_s`)
or fall back to the construction-time `default_timeout`. The gateway
also wraps each attempt in its own `asyncio.wait_for` as a safety net,
so this provider does not need to enforce a deadline itself.
"""

from __future__ import annotations

from typing import Any

import openai
from openai import AsyncOpenAI

from app._deprecated.providers.base import BaseAIProvider
from app._deprecated.providers.exceptions import (
    ProviderAuthenticationError,
    ProviderBadRequestError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app._deprecated.providers.models import (
    InferenceRequest,
    InferenceResponse,
    ProviderCapability,
    ProviderInfo,
    TokenUsage,
)

_PROVIDER_NAME = "openai"

_DEFAULT_CAPABILITIES = frozenset(
    {
        ProviderCapability.CHAT,
        ProviderCapability.TOOLS,
    }
)


class OpenAIProvider(BaseAIProvider):
    """OpenAI Chat Completions implementation of `BaseAIProvider`."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        default_timeout: float = 30.0,
        default_model: str | None = None,
    ) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=default_timeout,
        )
        self.info = ProviderInfo(
            name=_PROVIDER_NAME,
            capabilities=_DEFAULT_CAPABILITIES,
            default_model=default_model,
        )

    async def complete(self, request: InferenceRequest) -> InferenceResponse:
        try:
            response = await self._client.chat.completions.create(
                model=request.model,
                messages=self._to_openai_messages(request),
                temperature=request.temperature,
                max_tokens=request.max_output_tokens,
                timeout=request.timeout_s,
            )
        except openai.AuthenticationError as exc:
            raise ProviderAuthenticationError(str(exc), provider=_PROVIDER_NAME) from exc
        except openai.PermissionDeniedError as exc:
            raise ProviderAuthenticationError(str(exc), provider=_PROVIDER_NAME) from exc
        except openai.BadRequestError as exc:
            raise ProviderBadRequestError(str(exc), provider=_PROVIDER_NAME) from exc
        except openai.NotFoundError as exc:
            raise ProviderNotFoundError(str(exc), provider=_PROVIDER_NAME) from exc
        except openai.RateLimitError as exc:
            raise ProviderRateLimitError(str(exc), provider=_PROVIDER_NAME) from exc
        except openai.APITimeoutError as exc:
            raise ProviderTimeoutError(str(exc), provider=_PROVIDER_NAME) from exc
        except (openai.APIConnectionError, openai.InternalServerError) as exc:
            raise ProviderUnavailableError(str(exc), provider=_PROVIDER_NAME) from exc
        except openai.OpenAIError as exc:
            raise ProviderResponseError(str(exc), provider=_PROVIDER_NAME) from exc

        try:
            return self._to_inference_response(response)
        except (KeyError, AttributeError, IndexError, ValueError) as exc:
            raise ProviderResponseError(
                f"Malformed OpenAI response: {exc}",
                provider=_PROVIDER_NAME,
            ) from exc

    async def aclose(self) -> None:
        await self._client.close()

    # ─── Mapping helpers ──────────────────────────────────────────────

    @staticmethod
    def _to_openai_messages(request: InferenceRequest) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in request.messages:
            entry: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.name is not None:
                entry["name"] = m.name
            out.append(entry)
        return out

    @staticmethod
    def _to_inference_response(response: Any) -> InferenceResponse:
        choice = response.choices[0]
        content = choice.message.content or ""
        usage_obj = getattr(response, "usage", None)
        usage = TokenUsage(
            prompt_tokens=getattr(usage_obj, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage_obj, "completion_tokens", 0) or 0,
            total_tokens=getattr(usage_obj, "total_tokens", 0) or 0,
        )
        return InferenceResponse(
            content=content,
            model=getattr(response, "model", "") or "",
            finish_reason=getattr(choice, "finish_reason", None),
            usage=usage,
            raw={"id": getattr(response, "id", None)},
        )


__all__ = ["OpenAIProvider"]
