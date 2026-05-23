"""Abstract embedding-provider contract.

Identical discipline to `BaseAIProvider`: take a request, return a
response, or raise an `EmbeddingProviderError`. Providers DO NOT log
traces, DO NOT manage retries, DO NOT touch orchestration. The
embedding gateway owns those concerns and treats every provider
uniformly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.providers.embedding_models import (
    EmbeddingProviderInfo,
    EmbeddingRequest,
    EmbeddingResponse,
)


class BaseEmbeddingProvider(ABC):
    """Embedding provider contract.

    Subclasses MUST:

    * expose a concrete `info: EmbeddingProviderInfo` set during
      construction so the registry can advertise capabilities,
    * map every vendor exception onto an `EmbeddingProviderError`
      subclass — vendor exceptions MUST NOT escape `embed()`,
    * never log execution traces (the gateway emits the trace).
    """

    info: EmbeddingProviderInfo

    @property
    def name(self) -> str:
        return self.info.name

    @abstractmethod
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Encode a batch of texts into dense vectors."""

    async def aclose(self) -> None:
        """Optional shutdown hook for providers that hold network clients."""
        return None


__all__ = ["BaseEmbeddingProvider"]
