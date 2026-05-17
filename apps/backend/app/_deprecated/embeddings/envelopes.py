"""Embedding execution envelopes.

Mirrors `app/ai/envelopes.py`: the gateway always returns an envelope,
never raises. The trace is always present; result and error are
mutually exclusive.

Why this shape:

* Document ingestion can embed N batches concurrently via
  `asyncio.gather` and inspect every trace, including failed ones,
  without per-batch try/except gymnastics.
* The retrieval service can branch on `envelope.is_ok` to decide
  whether a degraded embedding result is still actionable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from app._deprecated.embeddings.exceptions import EmbeddingProviderError
from app._deprecated.embeddings.tracing import EmbeddingTrace

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class EmbeddingEnvelope(Generic[T]):
    """Result-or-error wrapper around one embedding execution.

    Invariant: exactly one of (`result`, `error`) is populated. The
    `trace` is always present.
    """

    trace: EmbeddingTrace
    result: T | None = None
    error: EmbeddingProviderError | None = None

    @property
    def is_ok(self) -> bool:
        return self.error is None and self.result is not None

    def unwrap(self) -> T:
        if self.error is not None:
            raise self.error
        if self.result is None:  # pragma: no cover — invariant violation
            raise RuntimeError("envelope has neither result nor error")
        return self.result


__all__ = ["EmbeddingEnvelope"]
