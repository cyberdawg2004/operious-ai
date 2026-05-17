"""Reranking envelope — never raises.

Same shape as every other envelope in the platform: trace is always
present, result is present iff `is_ok`. Future ML rerankers may fail
or time out; the envelope shape absorbs both cases without making
call sites branch on exception types.
"""

from __future__ import annotations

from dataclasses import dataclass

from app._deprecated.rag.reranking.models import RerankingResult
from app._deprecated.rag.reranking.tracing import RerankingTrace


@dataclass(frozen=True, slots=True)
class RerankingEnvelope:
    """Never-raising container around a reranker invocation."""

    trace: RerankingTrace
    result: RerankingResult | None = None
    error: BaseException | None = None

    @property
    def is_ok(self) -> bool:
        return self.error is None and self.result is not None

    def unwrap(self) -> RerankingResult:
        if not self.is_ok:
            raise RuntimeError(
                "RerankingEnvelope.unwrap() called on a failed envelope; "
                "inspect .trace and .error first."
            ) from self.error
        assert self.result is not None
        return self.result


__all__ = ["RerankingEnvelope"]
