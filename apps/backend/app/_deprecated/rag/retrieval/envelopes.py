"""Retrieval runtime envelope — never raises.

Same pattern as `ExecutionEnvelope` / `EmbeddingEnvelope` /
`RetrievalEnvelope`: the runtime always returns one of these. Callers
inspect `is_ok`, then either `unwrap()` to obtain the candidate set or
read the trace to attribute the failure.
"""

from __future__ import annotations

from dataclasses import dataclass

from app._deprecated.rag.retrieval.models import RetrievalCandidateSet
from app._deprecated.rag.retrieval.tracing import RetrievalRuntimeTrace


@dataclass(frozen=True, slots=True)
class RetrievalRuntimeEnvelope:
    """Never-raising container around a retrieval-runtime outcome."""

    trace: RetrievalRuntimeTrace
    result: RetrievalCandidateSet | None = None
    error: BaseException | None = None

    @property
    def is_ok(self) -> bool:
        return self.error is None and self.result is not None

    def unwrap(self) -> RetrievalCandidateSet:
        if not self.is_ok:
            raise RuntimeError(
                "RetrievalRuntimeEnvelope.unwrap() called on a failed envelope; "
                "inspect .trace and .error first."
            ) from self.error
        assert self.result is not None
        return self.result


__all__ = ["RetrievalRuntimeEnvelope"]
