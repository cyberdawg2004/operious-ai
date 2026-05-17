"""Abstract provider contract.

A provider is a narrow object: take a request, return a response, or
raise a typed `AIProviderError`. It does NOT own retries, timeouts,
tracing, or orchestration policy. It does NOT log execution metadata.
Those concerns live in the gateway and the observability layer.

`aclose` is an optional lifecycle hook so providers that hold network
clients (most do) can shut them down cleanly when the application
disposes the registry on process exit.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app._deprecated.providers.models import InferenceRequest, InferenceResponse, ProviderInfo


class BaseAIProvider(ABC):
    """Inference provider contract.

    Subclasses MUST:

    * expose a concrete `info: ProviderInfo` attribute set during
      construction so the registry can advertise capabilities,
    * map every vendor exception onto an `AIProviderError` subclass,
    * never log execution traces themselves — that is the gateway's job.
    """

    info: ProviderInfo

    @property
    def name(self) -> str:
        """Convenience: the provider's registered identifier."""
        return self.info.name

    @abstractmethod
    async def complete(self, request: InferenceRequest) -> InferenceResponse:
        """Execute one chat-completion request.

        MUST raise an `AIProviderError` subclass on failure; vendor
        exceptions MUST NOT escape this method.
        """

    async def aclose(self) -> None:
        """Optional shutdown hook.

        Override if the provider holds resources (HTTP clients, sockets,
        connection pools) that need explicit disposal.
        """
        return None


__all__ = ["BaseAIProvider"]
