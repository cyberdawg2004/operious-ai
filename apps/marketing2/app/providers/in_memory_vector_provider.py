"""Deterministic in-memory vector provider.

The Sprint G default. Two architectural roles:

1. *Substrate for development and CI.* Same code path as a real vector
   DB; same `(name, dimensions, records)` lifecycle; same query shape.
   Tests can use the in-memory provider with full confidence that
   results are reproducible.
2. *Reference implementation* for the `BaseVectorProvider` contract.
   When adding pgvector / Pinecone / Qdrant later, the in-memory
   provider is the spec they must agree with.

Determinism is enforced two ways:
* Cosine similarity is computed in pure Python with stable arithmetic.
* On score ties (very common with small dev datasets), hits are
  ordered by `record.id` (ascending UUID) so the output is byte-for-
  byte identical between runs.

Performance note: pure Python is fine up to ~10k records / 1500-dim
vectors (sub-second). When real load arrives, the in-memory provider
is retired in favour of pgvector — not optimised in place.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from typing import Any, Mapping, Sequence

from app.providers.vector_base import BaseVectorProvider
from app.providers.vector_exceptions import (
    VectorIndexDimensionMismatchError,
    VectorIndexNotFoundError,
)
from app.providers.vector_models import (
    VectorDistance,
    VectorHit,
    VectorProviderCapability,
    VectorProviderInfo,
    VectorQuery,
    VectorRecord,
)

_PROVIDER_NAME = "in_memory"

_CAPABILITIES = frozenset(
    {
        VectorProviderCapability.UPSERT,
        VectorProviderCapability.DELETE,
        VectorProviderCapability.METADATA_FILTER,
    }
)


class _Index:
    """One in-memory index keyed by UUID."""

    __slots__ = ("name", "dimensions", "records")

    def __init__(self, name: str, dimensions: int) -> None:
        self.name = name
        self.dimensions = dimensions
        self.records: dict[uuid.UUID, VectorRecord] = {}


class InMemoryVectorProvider(BaseVectorProvider):
    """Pure-Python deterministic vector provider.

    The provider lock serialises mutating operations so concurrent
    upserts from inside one process can't race. Even with the lock the
    provider stays well under millisecond-scale for the dataset sizes
    Sprint G expects.
    """

    def __init__(self) -> None:
        self._indexes: dict[str, _Index] = {}
        self._lock = asyncio.Lock()
        self.info = VectorProviderInfo(
            name=_PROVIDER_NAME,
            capabilities=_CAPABILITIES,
            distance=VectorDistance.COSINE,
        )

    # ─── Lifecycle ────────────────────────────────────────────────────

    async def ensure_index(self, name: str, *, dimensions: int) -> None:
        if dimensions <= 0:
            raise ValueError(f"dimensions must be > 0, got {dimensions}")
        async with self._lock:
            existing = self._indexes.get(name)
            if existing is None:
                self._indexes[name] = _Index(name, dimensions)
                return
            if existing.dimensions != dimensions:
                raise VectorIndexDimensionMismatchError(
                    f"index '{name}' exists with dimensions={existing.dimensions}, "
                    f"got {dimensions}",
                    provider=_PROVIDER_NAME,
                )

    # ─── Mutation ─────────────────────────────────────────────────────

    async def upsert(
        self,
        index: str,
        records: Sequence[VectorRecord],
    ) -> None:
        async with self._lock:
            idx = self._require_index(index)
            for record in records:
                if len(record.vector) != idx.dimensions:
                    raise VectorIndexDimensionMismatchError(
                        f"record vector dimension {len(record.vector)} != "
                        f"index dimension {idx.dimensions}",
                        provider=_PROVIDER_NAME,
                    )
                idx.records[record.id] = record

    async def delete(
        self,
        index: str,
        ids: Sequence[uuid.UUID],
    ) -> None:
        async with self._lock:
            idx = self._require_index(index)
            for record_id in ids:
                idx.records.pop(record_id, None)

    # ─── Read ─────────────────────────────────────────────────────────

    async def query(
        self,
        index: str,
        query: VectorQuery,
    ) -> Sequence[VectorHit]:
        # Snapshot under the lock so the scoring loop sees a consistent
        # view, then drop the lock for the (CPU-bound) computation.
        async with self._lock:
            idx = self._require_index(index)
            if len(query.vector) != idx.dimensions:
                raise VectorIndexDimensionMismatchError(
                    f"query vector dimension {len(query.vector)} != "
                    f"index dimension {idx.dimensions}",
                    provider=_PROVIDER_NAME,
                )
            candidates = list(idx.records.values())

        candidates = [r for r in candidates if _matches_filter(r.metadata, query.filter)]
        if not candidates:
            return ()

        query_norm = _l2_norm(query.vector)
        if query_norm == 0.0:
            return ()

        scored: list[tuple[float, uuid.UUID, VectorRecord]] = []
        for record in candidates:
            rnorm = _l2_norm(record.vector)
            if rnorm == 0.0:
                score = 0.0
            else:
                score = _dot(query.vector, record.vector) / (query_norm * rnorm)
            scored.append((score, record.id, record))

        # Sort by (-score, id) so highest score wins; ties resolved by
        # ascending UUID — fully deterministic.
        scored.sort(key=lambda t: (-t[0], t[1]))
        top = scored[: max(0, query.top_k)]
        return tuple(
            VectorHit(id=record.id, score=score, metadata=dict(record.metadata))
            for score, _, record in top
        )

    # ─── Introspection (test / debug aid) ─────────────────────────────

    def size(self, index: str) -> int:
        """Return the number of records currently stored in `index`."""
        idx = self._indexes.get(index)
        return 0 if idx is None else len(idx.records)

    def indexes(self) -> tuple[str, ...]:
        return tuple(sorted(self._indexes.keys()))

    # ─── Internals ────────────────────────────────────────────────────

    def _require_index(self, name: str) -> _Index:
        idx = self._indexes.get(name)
        if idx is None:
            raise VectorIndexNotFoundError(
                f"index '{name}' does not exist", provider=_PROVIDER_NAME
            )
        return idx


# ─── Pure-function math helpers ───────────────────────────────────────


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _l2_norm(v: Sequence[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def _matches_filter(metadata: Mapping[str, Any], filter_: Mapping[str, Any]) -> bool:
    """Conjunctive key-equality filter.

    Provider-portable: every vector backend in the ecosystem supports
    exact-match filtering. Richer DSLs are deferred until we know which
    vendor's language to mirror.
    """
    if not filter_:
        return True
    for key, expected in filter_.items():
        if metadata.get(key) != expected:
            return False
    return True


__all__ = ["InMemoryVectorProvider"]
