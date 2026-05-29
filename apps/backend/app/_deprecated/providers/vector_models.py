"""Vendor-neutral vector-provider contract types.

`VectorRecord` is what callers upsert. `VectorQuery` is what callers
ask. `VectorHit` is what providers return. The vector itself is
always a `tuple[float, ...]` so it survives JSON round-trips and so
its hashability / immutability is enforced.

`metadata` is a free-form JSON-serialisable mapping. Sprint G uses it
for `chunk_id`, `document_id`, and other bookkeeping. Future sprints
can add `tenant_id`, `tags`, etc., without API changes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class VectorRecord:
    """One vector + its metadata, addressed by `id`.

    `id` is provided by the caller (typically `chunk_id`) so the
    record's identity is durable across vector-store migrations. The
    vector itself is a tuple to enforce immutability — accidental
    mutation between upsert and query would be a near-impossible bug
    to diagnose.
    """

    id: uuid.UUID
    vector: tuple[float, ...]
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class VectorQuery:
    """One query: vector + top_k.

    `filter` is a key-equality predicate over record metadata (e.g.
    `{"document_id": "..."}`). Providers that support richer DSLs may
    interpret this differently in later sprints; today every provider
    treats it as conjunctive equality.
    """

    vector: tuple[float, ...]
    top_k: int = 10
    filter: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class VectorHit:
    """One result row from a vector query."""

    id: uuid.UUID
    score: float
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


class VectorDistance(str, Enum):
    """Distance metrics supported by providers."""
    COSINE = "cosine"
    DOT = "dot"
    EUCLIDEAN = "euclidean"


class VectorProviderCapability(str, Enum):
    """Coarse-grained capabilities advertised per provider."""
    UPSERT = "upsert"
    DELETE = "delete"
    METADATA_FILTER = "metadata_filter"
    PERSISTENT = "persistent"


@dataclass(frozen=True, slots=True)
class VectorProviderInfo:
    """Identity + capability descriptor for a vector provider."""
    name: str
    capabilities: frozenset[VectorProviderCapability]
    distance: VectorDistance = VectorDistance.COSINE


__all__ = [
    "VectorRecord",
    "VectorQuery",
    "VectorHit",
    "VectorDistance",
    "VectorProviderCapability",
    "VectorProviderInfo",
]
