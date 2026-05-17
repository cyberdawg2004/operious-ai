"""Retrieval envelope.

The retrieval service never raises. It either returns a populated
`RetrievalResult` wrapped in an envelope, or an envelope carrying the
specific error (embedding failure, vector failure, validation error).

The envelope also carries the embedding sub-trace so consumers can
read the per-attempt embedding diagnostics without separately
consulting the structured logs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app._deprecated.embeddings.tracing import EmbeddingTrace
from app._deprecated.memory.retrieval.models import RetrievalResult


@dataclass(frozen=True, slots=True)
class RetrievalEnvelope:
    """Result-or-error wrapper around one retrieval call.

    Invariant: exactly one of (`result`, `error`) is populated.
    """

    result: RetrievalResult | None = None
    error: Exception | None = None
    embedding_trace: EmbeddingTrace | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_ok(self) -> bool:
        return self.error is None and self.result is not None

    def unwrap(self) -> RetrievalResult:
        if self.error is not None:
            raise self.error
        if self.result is None:  # pragma: no cover — invariant
            raise RuntimeError("envelope has neither result nor error")
        return self.result


__all__ = ["RetrievalEnvelope"]
