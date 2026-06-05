"""Tenant knowledge embedding adapter boundary."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Final, Protocol, cast, runtime_checkable

import httpx

from app.core.http import get_shared_http_client

if TYPE_CHECKING:
    from app.core.config import Settings

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
DEFAULT_EMBEDDING_DIMENSIONS: Final[int] = 1536

# Default output dimensions per OpenAI embedding model (used for storage
# metadata; the actual vector length comes from the API response).
_OPENAI_MODEL_DIMENSIONS: Final[dict[str, int]] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


@runtime_checkable
class KnowledgeEmbeddingProvider(Protocol):
    """Provider-agnostic embedding adapter contract.

    The deterministic provider remains available for tests and explicit
    fallback, while production composition can select a real provider through
    ``build_embedding_provider``.
    """

    provider_name: str
    model_name: str
    dimensions: int

    async def embed_texts(
        self,
        *,
        tenant_id: str,
        texts: Sequence[str],
    ) -> tuple[tuple[float, ...], ...]: ...


class DeterministicHashEmbeddingProvider:
    """Small deterministic token-hash embedding provider.

    The provider has no network path and no credentials. It produces a
    stable normalized bag-of-tokens vector, which is sufficient for the
    Phase 5-A vector-store and replay contracts.
    """

    provider_name = "deterministic_hash"
    model_name = "operious-hash-embedding-v1"

    def __init__(self, *, dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be > 0")
        self.dimensions = dimensions

    async def embed_texts(
        self,
        *,
        tenant_id: str,
        texts: Sequence[str],
    ) -> tuple[tuple[float, ...], ...]:
        if not tenant_id:
            raise ValueError("tenant_id must be non-empty")
        return tuple(self._embed(text) for text in texts)

    def _embed(self, text: str) -> tuple[float, ...]:
        vector = [0.0 for _ in range(self.dimensions)]
        for token in _tokens(text):
            digest = hashlib.sha256(
                f"{self.model_name}|{token}".encode("utf-8")
            ).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return tuple(vector)
        return tuple(value / norm for value in vector)


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(match.group(0).lower() for match in _TOKEN_RE.finditer(text))


class OpenAIEmbeddingProvider:
    """Real OpenAI embeddings adapter over HTTP (no vendor SDK).

    Mirrors the substrate's :class:`AnthropicMessagesClient` convention: a thin
    httpx adapter that can take an injected client for testing. Produces real
    semantic embeddings, replacing deterministic hash embeddings in production.
    """

    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "text-embedding-3-small",
        dimensions: int | None = None,
        base_url: str = "https://api.openai.com",
        timeout_seconds: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("OPENAI_API_KEY is not configured")
        if not model.strip():
            raise ValueError("OpenAI embedding model must be non-empty")
        self._api_key = api_key
        self.model_name = model
        if dimensions is not None and dimensions <= 0:
            raise ValueError("OpenAI embedding dimensions must be > 0")
        # Explicit dimensions are sent to the API (text-embedding-3-* support
        # truncation); otherwise the model's native dimension is used for
        # storage metadata.
        self._explicit_dimensions = dimensions
        self.dimensions = dimensions or _OPENAI_MODEL_DIMENSIONS.get(model, 1536)
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client

    async def embed_texts(
        self,
        *,
        tenant_id: str,
        texts: Sequence[str],
    ) -> tuple[tuple[float, ...], ...]:
        if not tenant_id:
            raise ValueError("tenant_id must be non-empty")
        items = list(texts)
        if not items:
            return ()
        payload: dict[str, Any] = {"model": self.model_name, "input": items}
        if self._explicit_dimensions is not None:
            payload["dimensions"] = self._explicit_dimensions
        client = self._http_client or get_shared_http_client()
        response = await client.post(
            f"{self._base_url}/v1/embeddings",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "content-type": "application/json",
            },
            json=payload,
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        data = cast(list[dict[str, Any]], response.json()["data"])
        ordered = sorted(data, key=lambda row: int(row["index"]))
        embeddings = tuple(
            tuple(float(value) for value in cast(Sequence[Any], row["embedding"]))
            for row in ordered
        )
        mismatched = [
            len(embedding)
            for embedding in embeddings
            if len(embedding) != self.dimensions
        ]
        if mismatched:
            raise ValueError(
                "OpenAI embedding response dimension mismatch: "
                f"expected {self.dimensions}, got {mismatched[0]}"
            )
        return embeddings


def build_embedding_provider(settings: "Settings") -> KnowledgeEmbeddingProvider:
    """Select the embedding provider from configuration.

    Returns the real :class:`OpenAIEmbeddingProvider` when
    ``EMBEDDING_DEFAULT_PROVIDER == "openai"`` and an API key is set; otherwise
    the deterministic hash provider (dev / CI / unconfigured). This is the single
    point that honours ``EMBEDDING_DEFAULT_PROVIDER``; call sites must use it
    rather than instantiating a provider directly.
    """
    target_dimensions = (
        settings.OPENAI_EMBEDDING_DIMENSIONS
        if settings.OPENAI_EMBEDDING_DIMENSIONS is not None
        else DEFAULT_EMBEDDING_DIMENSIONS
    )
    if target_dimensions != DEFAULT_EMBEDDING_DIMENSIONS:
        raise ValueError(
            "OPENAI_EMBEDDING_DIMENSIONS must match native pgvector "
            f"dimension {DEFAULT_EMBEDDING_DIMENSIONS}; got {target_dimensions}"
        )
    provider = settings.EMBEDDING_DEFAULT_PROVIDER.strip().casefold()
    api_key = (settings.OPENAI_API_KEY or "").strip()
    if provider == "openai" and api_key:
        return OpenAIEmbeddingProvider(
            api_key=api_key,
            model=settings.OPENAI_EMBEDDING_MODEL,
            dimensions=target_dimensions,
            base_url=settings.OPENAI_BASE_URL or "https://api.openai.com",
            timeout_seconds=settings.EMBEDDING_TIMEOUT_SECONDS,
        )
    return DeterministicHashEmbeddingProvider(dimensions=target_dimensions)


__all__ = [
    "DEFAULT_EMBEDDING_DIMENSIONS",
    "DeterministicHashEmbeddingProvider",
    "KnowledgeEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "build_embedding_provider",
]
