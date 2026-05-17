"""OpenAI embedding provider.

The ONLY file in the codebase allowed to import the OpenAI embeddings
SDK. Every vendor exception is mapped to the platform's
`EmbeddingProviderError` hierarchy; every vendor field is normalised
onto `EmbeddingResponse`.

Provider/SDK collision avoidance: the chat-completion provider
(`openai_provider.py`) and this file each construct their own
`AsyncOpenAI` client. Keeping the clients separate means the embedding
client can use a different `base_url` (proxy, embedding-only gateway)
later without disturbing chat traffic.
"""

from __future__ import annotations

from typing import Any

import openai
from openai import AsyncOpenAI

from app._deprecated.providers.embedding_base import BaseEmbeddingProvider
from app._deprecated.providers.embedding_exceptions import (
    EmbeddingAuthenticationError,
    EmbeddingBadRequestError,
    EmbeddingNotFoundError,
    EmbeddingProviderError,
    EmbeddingRateLimitError,
    EmbeddingResponseError,
    EmbeddingTimeoutError,
    EmbeddingUnavailableError,
)
from app._deprecated.providers.embedding_models import (
    EmbeddingProviderCapability,
    EmbeddingProviderInfo,
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingUsage,
)

_PROVIDER_NAME = "openai"

_DEFAULT_CAPABILITIES = frozenset(
    {
        EmbeddingProviderCapability.DENSE,
        EmbeddingProviderCapability.BATCH,
        EmbeddingProviderCapability.DIMENSIONS_REDUCTION,
    }
)


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI Embeddings API implementation of `BaseEmbeddingProvider`."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        default_timeout: float = 30.0,
        default_model: str | None = None,
        default_dimensions: int | None = None,
    ) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=default_timeout,
        )
        self.info = EmbeddingProviderInfo(
            name=_PROVIDER_NAME,
            capabilities=_DEFAULT_CAPABILITIES,
            default_model=default_model,
            default_dimensions=default_dimensions,
        )

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        if not request.texts:
            raise EmbeddingBadRequestError(
                "embedding request has no texts", provider=_PROVIDER_NAME
            )

        kwargs: dict[str, Any] = {
            "model": request.model,
            "input": list(request.texts),
        }
        if request.dimensions is not None:
            kwargs["dimensions"] = request.dimensions
        if request.timeout_s is not None:
            kwargs["timeout"] = request.timeout_s

        try:
            response = await self._client.embeddings.create(**kwargs)
        except openai.AuthenticationError as exc:
            raise EmbeddingAuthenticationError(str(exc), provider=_PROVIDER_NAME) from exc
        except openai.PermissionDeniedError as exc:
            raise EmbeddingAuthenticationError(str(exc), provider=_PROVIDER_NAME) from exc
        except openai.BadRequestError as exc:
            raise EmbeddingBadRequestError(str(exc), provider=_PROVIDER_NAME) from exc
        except openai.NotFoundError as exc:
            raise EmbeddingNotFoundError(str(exc), provider=_PROVIDER_NAME) from exc
        except openai.RateLimitError as exc:
            raise EmbeddingRateLimitError(str(exc), provider=_PROVIDER_NAME) from exc
        except openai.APITimeoutError as exc:
            raise EmbeddingTimeoutError(str(exc), provider=_PROVIDER_NAME) from exc
        except (openai.APIConnectionError, openai.InternalServerError) as exc:
            raise EmbeddingUnavailableError(str(exc), provider=_PROVIDER_NAME) from exc
        except openai.OpenAIError as exc:
            raise EmbeddingResponseError(str(exc), provider=_PROVIDER_NAME) from exc

        try:
            return self._to_embedding_response(response)
        except (KeyError, AttributeError, IndexError, ValueError, TypeError) as exc:
            raise EmbeddingResponseError(
                f"malformed OpenAI embedding response: {exc}",
                provider=_PROVIDER_NAME,
            ) from exc

    async def aclose(self) -> None:
        await self._client.close()

    # ─── Mapping helpers ──────────────────────────────────────────────

    @staticmethod
    def _to_embedding_response(response: Any) -> EmbeddingResponse:
        # `data` is parallel to the request `input` list, but the vendor
        # documents that we should sort by `.index` to be safe.
        data = sorted(response.data, key=lambda r: r.index)
        vectors = tuple(tuple(float(x) for x in row.embedding) for row in data)
        dimensions = len(vectors[0]) if vectors else 0

        usage_obj = getattr(response, "usage", None)
        usage = EmbeddingUsage(
            prompt_tokens=getattr(usage_obj, "prompt_tokens", 0) or 0,
            total_tokens=getattr(usage_obj, "total_tokens", 0) or 0,
        )
        return EmbeddingResponse(
            vectors=vectors,
            model=getattr(response, "model", "") or "",
            dimensions=dimensions,
            usage=usage,
        )


__all__ = ["OpenAIEmbeddingProvider"]
