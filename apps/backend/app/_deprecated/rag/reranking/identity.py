"""Identity reranker — pass-through.

Returns input candidates in unchanged order. The default reranker for
the assembly pipeline so the runtime always emits a `RerankingEnvelope`
with a populated trace, regardless of whether a real reranker has been
configured.

Deterministic by construction.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app._deprecated.rag.reranking.base import BaseReranker
from app._deprecated.rag.reranking.envelopes import RerankingEnvelope
from app._deprecated.rag.reranking.models import RerankingRequest, RerankingResult


class IdentityReranker(BaseReranker):
    """Pass-through reranker. Preserves input order exactly."""

    name = "identity"

    async def rerank(
        self,
        request: RerankingRequest,
        *,
        request_id: str | None = None,
    ) -> RerankingEnvelope:
        loop = asyncio.get_event_loop()
        started_at = datetime.now(timezone.utc)
        loop_start = loop.time()
        result = RerankingResult(
            candidates=request.candidates,
            reranker_name=self.name,
            input_count=len(request.candidates),
            output_count=len(request.candidates),
        )
        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000, 2)
        return self._wrap_success(
            result,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
        )


__all__ = ["IdentityReranker"]
