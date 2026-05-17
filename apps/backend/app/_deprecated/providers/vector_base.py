"""Abstract vector-provider contract.

Four methods, no more. Anything richer (re-ranking, hybrid search,
metadata-filter DSL) is a retrieval *service* concern, not a vector
provider concern. Keeping the contract this narrow is what lets a
real vector DB (pgvector, Pinecone, Qdrant) be added later without
the rest of the codebase changing.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Sequence

from app._deprecated.providers.vector_models import (
    VectorHit,
    VectorProviderInfo,
    VectorQuery,
    VectorRecord,
)


class BaseVectorProvider(ABC):
    """Vector storage adapter.

    Concrete providers:

    * map vendor errors onto `VectorProviderError` subclasses,
    * never log traces themselves — the retrieval / ingestion service
      logs at the operation level (per-document, per-query),
    * never own orchestration.
    """

    info: VectorProviderInfo

    @property
    def name(self) -> str:
        return self.info.name

    @abstractmethod
    async def ensure_index(self, name: str, *, dimensions: int) -> None:
        """Ensure an index exists with the declared dimensionality.

        Idempotent: calling repeatedly with the same `(name, dimensions)`
        succeeds. Calling with a mismatched dimensionality on an
        existing index MUST raise `VectorIndexDimensionMismatchError`.
        """

    @abstractmethod
    async def upsert(
        self,
        index: str,
        records: Sequence[VectorRecord],
    ) -> None:
        """Insert or update records by id."""

    @abstractmethod
    async def query(
        self,
        index: str,
        query: VectorQuery,
    ) -> Sequence[VectorHit]:
        """Return the top-K hits ranked by similarity."""

    @abstractmethod
    async def delete(
        self,
        index: str,
        ids: Sequence[uuid.UUID],
    ) -> None:
        """Remove records by id. No-op for ids that are absent."""

    async def aclose(self) -> None:
        """Optional shutdown hook for providers that hold network clients."""
        return None


__all__ = ["BaseVectorProvider"]
