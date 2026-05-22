"""Tenant knowledge embedding adapter boundary."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


@runtime_checkable
class KnowledgeEmbeddingProvider(Protocol):
    """Provider-agnostic embedding adapter contract.

    Phase 5-A ships a deterministic local provider so ingestion and
    retrieval are replayable without platform or tenant credentials.
    Real provider integration is reserved for Phase 5-C.
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

    def __init__(self, *, dimensions: int = 32) -> None:
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


__all__ = [
    "DeterministicHashEmbeddingProvider",
    "KnowledgeEmbeddingProvider",
]
