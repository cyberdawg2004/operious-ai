"""Single-query retrieval strategy.

Wraps the Sprint G `RetrievalService` with the Sprint H candidate
contract. One embedding + one vector query → a sequence of
`RetrievalCandidate`s.

This strategy is the reference implementation: every other future
strategy follows the same outer shape — translate inputs into the
underlying service's request, await an envelope, lift hits into
candidates, attach attribution, return.

The strategy never reaches for the vector provider directly. The
`RetrievalService` owns that coupling.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.memory.retrieval.models import RetrievalQuery
from app.memory.retrieval.service import RetrievalService, RetrievalValidationError
from app.rag.retrieval.base import BaseRetrievalStrategy, StrategyExecutionResult
from app.rag.retrieval.models import (
    RetrievalCandidate,
    RetrievalRuntimeRequest,
    RetrievalStrategyInfo,
)


class SingleQueryStrategy(BaseRetrievalStrategy):
    """Single embedding → single vector query → flat candidate list."""

    info = RetrievalStrategyInfo(
        name="single_query",
        description=(
            "Embed the query once, run a single top-K vector query, "
            "lift hits into candidates. Deterministic given a "
            "deterministic vector provider."
        ),
    )

    def __init__(self, retrieval_service: RetrievalService) -> None:
        self._retrieval_service = retrieval_service

    async def execute(
        self,
        request: RetrievalRuntimeRequest,
        *,
        request_id: str | None,
    ) -> StrategyExecutionResult:
        policy = request.policy
        metadata: Mapping[str, Any] = {
            "rag_strategy": self.info.name,
            "policy_id": policy.policy_id,
            "tenant_scope": policy.tenant_scope,
            **dict(request.metadata),
        }

        envelope = await self._retrieval_service.retrieve(
            RetrievalQuery(
                text=request.query,
                top_k=policy.top_k,
                filter=dict(policy.metadata_filter),
            ),
            metadata=metadata,
            request_id=request_id,
        )

        # The runtime catches strategy exceptions, so we surface
        # retrieval-service envelope failures by raising — the runtime
        # folds the error into its own envelope.
        if not envelope.is_ok or envelope.result is None:
            if envelope.error is not None:
                raise envelope.error
            raise RetrievalValidationError(
                "single_query strategy: retrieval envelope reported "
                "no result and no error (envelope contract violation)."
            )

        result = envelope.result
        candidates = tuple(
            RetrievalCandidate(
                chunk_id=hit.chunk_id,
                document_id=hit.document_id,
                ordinal=hit.ordinal,
                score=hit.score,
                content=hit.content,
                source=self._extract_source(hit.metadata),
                source_strategy=self.info.name,
                strategy_rank=rank,
                metadata=dict(hit.metadata),
            )
            for rank, hit in enumerate(result.hits)
        )

        return StrategyExecutionResult(
            candidates=candidates,
            embedding_trace=envelope.embedding_trace,
        )

    @staticmethod
    def _extract_source(metadata: Mapping[str, Any]) -> str | None:
        value = metadata.get("source") or metadata.get("document_source")
        return str(value) if value is not None else None


__all__ = ["SingleQueryStrategy"]
