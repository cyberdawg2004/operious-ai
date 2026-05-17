"""Reranker contract.

Every concrete reranker subclasses this and implements `rerank()`. The
method returns a `RerankingEnvelope`; concrete rerankers never let
exceptions escape — the base class provides a small wrapper helper for
that pattern, but subclasses MAY produce their own envelopes when they
have richer trace metadata to carry.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from app._deprecated.rag.reranking.envelopes import RerankingEnvelope
from app._deprecated.rag.reranking.models import RerankingRequest, RerankingResult
from app._deprecated.rag.reranking.tracing import RerankingTrace


class BaseReranker(ABC):
    """Abstract reranker. Stateless across calls."""

    name: str

    @abstractmethod
    async def rerank(
        self,
        request: RerankingRequest,
        *,
        request_id: str | None = None,
    ) -> RerankingEnvelope:
        """Rerank `request.candidates` and return an envelope."""

    # ─── Reusable envelope helpers ───────────────────────────────────

    def _wrap_success(
        self,
        result: RerankingResult,
        *,
        started_at: datetime,
        ended_at: datetime,
        latency_ms: float,
    ) -> RerankingEnvelope:
        return RerankingEnvelope(
            trace=RerankingTrace(
                reranker_name=self.name,
                status="ok",
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=latency_ms,
                input_count=result.input_count,
                output_count=result.output_count,
            ),
            result=result,
        )

    def _wrap_failure(
        self,
        error: BaseException,
        *,
        input_count: int,
        started_at: datetime,
        ended_at: datetime,
        latency_ms: float,
    ) -> RerankingEnvelope:
        return RerankingEnvelope(
            trace=RerankingTrace(
                reranker_name=self.name,
                status="failed",
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=latency_ms,
                input_count=input_count,
                output_count=0,
                error=f"{type(error).__name__}: {error}",
            ),
            error=error,
        )

    @staticmethod
    def _now() -> tuple[datetime, float]:
        return datetime.now(timezone.utc), asyncio.get_event_loop().time()


__all__ = ["BaseReranker"]
