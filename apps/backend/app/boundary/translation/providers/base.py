"""Translation provider abstract interface.

Translation providers convert a customer-language payload to
canonical English (ingress) or canonical English to customer
language (egress).

The interface is intentionally minimal:

* providers MUST be async and pure with respect to the inputs;
* providers MUST NOT mutate global state or perform retries;
* providers MUST be replaceable — caller controls retries +
  observability outside of the substrate.

Real production providers belong outside this module. Inside
the boundary substrate we ship one **deterministic identity**
provider and one **deterministic stub** provider for tests.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.boundary.translation.enums import (
    TranslationProviderKind,
)
from app.boundary.translation.models.payload import (
    TranslationPayload,
)


@dataclass(frozen=True, slots=True)
class TranslationProviderRequest:
    """Provider input."""

    source: TranslationPayload
    target_language: str

    def __post_init__(self) -> None:
        if not self.target_language:
            raise ValueError(
                "TranslationProviderRequest.target_language must "
                "be non-empty"
            )


@dataclass(frozen=True, slots=True)
class TranslationProviderResponse:
    """Provider output."""

    translated: TranslationPayload
    provider_name: str

    def __post_init__(self) -> None:
        if not self.provider_name:
            raise ValueError(
                "TranslationProviderResponse.provider_name must "
                "be non-empty"
            )


class BaseTranslationProvider(ABC):
    """Abstract translation-provider interface."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable provider name (used in lineage / replay)."""

    @property
    @abstractmethod
    def kind(self) -> TranslationProviderKind:
        """Provider classification."""

    @abstractmethod
    async def translate(
        self, request: TranslationProviderRequest
    ) -> TranslationProviderResponse:
        """Return ``TranslationProviderResponse`` for the request."""


__all__ = [
    "BaseTranslationProvider",
    "TranslationProviderRequest",
    "TranslationProviderResponse",
]
