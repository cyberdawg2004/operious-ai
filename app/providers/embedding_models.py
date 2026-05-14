"""Vendor-neutral embedding contract types.

The shapes downstream code (gateway, ingestion service, retrieval
service) consumes. Vendor specifics — OpenAI's `input` field name,
their per-record response shape — never leak past the concrete
provider that translates them.

Frozen dataclasses everywhere: embedding requests flow into retries
and traces, where accidental in-flight mutation would be catastrophic
for reproducibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class EmbeddingUsage:
    """Vendor-neutral token-accounting bucket for embedding calls."""
    prompt_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    """Vendor-neutral embedding request.

    `texts` is a batch — most embedding APIs accept up to a few hundred
    inputs per call, which is dramatically more efficient than one
    request per text. The gateway / service decides batching.

    `dimensions` is optional and only honoured by models that support
    output-size reduction (e.g. `text-embedding-3-*`). When None, the
    provider returns the model's native dimensionality.
    """

    texts: tuple[str, ...]
    model: str
    dimensions: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    timeout_s: float | None = None


@dataclass(frozen=True, slots=True)
class EmbeddingResponse:
    """Vendor-neutral embedding response.

    `vectors` is parallel to the request's `texts` tuple — same length,
    same order. `dimensions` is the actual output dimension (which may
    differ from the request when the vendor enforces a minimum).
    """

    vectors: tuple[tuple[float, ...], ...]
    model: str
    dimensions: int
    usage: EmbeddingUsage = field(default_factory=EmbeddingUsage)
    raw: Mapping[str, Any] | None = None


class EmbeddingProviderCapability(str, Enum):
    """Coarse-grained capability flags advertised by each provider."""
    DENSE = "dense"           # standard dense vector embeddings
    SPARSE = "sparse"         # reserved for future hybrid retrieval
    BATCH = "batch"           # provider supports >1 text per request
    DIMENSIONS_REDUCTION = "dimensions_reduction"


@dataclass(frozen=True, slots=True)
class EmbeddingProviderInfo:
    """Identity + capability descriptor for an embedding provider."""
    name: str
    capabilities: frozenset[EmbeddingProviderCapability]
    default_model: str | None = None
    default_dimensions: int | None = None


__all__ = [
    "EmbeddingUsage",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "EmbeddingProviderCapability",
    "EmbeddingProviderInfo",
]
