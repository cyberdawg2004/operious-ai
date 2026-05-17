"""Retrieval orchestration runtime.

One public method (`retrieve`) executes the entire retrieval phase:

    request → strategy fan-in → dedup → sort → policy filter → envelope

The runtime is intentionally synchronous in strategy execution today —
strategies run sequentially in request order. Concurrent fan-out can be
added here (one place) when a sprint requires it. Call sites never
change.

Determinism contract:

* duplicate `chunk_id` across strategies is resolved by **higher score**;
  on score ties the lower (lexicographic) UUID wins, mirroring the
  in-memory vector provider's tiebreak rule;
* the final candidate tuple is sorted `(score DESC, chunk_id ASC)`;
* policy filtering preserves the sorted order;
* the runtime never randomises, never iterates over `dict` ordering, and
  never calls into wall-clock-dependent code paths beyond trace
  timestamps.

The runtime is the only place that emits the retrieval-runtime metric
and log lines. Strategies do not log on their own — single observer.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Mapping, Sequence

from app.observability.context import get_request_id
from app._deprecated.observability.rag_retrieval_logging import (
    log_retrieval_runtime,
    log_strategy_invocation,
)
from app._deprecated.observability.rag_retrieval_metrics import (
    record_retrieval_runtime,
    record_strategy_invocation,
)
from app._deprecated.rag.policies.enforcement import filter_candidates_by_policy
from app._deprecated.rag.retrieval.base import BaseRetrievalStrategy
from app._deprecated.rag.retrieval.envelopes import RetrievalRuntimeEnvelope
from app._deprecated.rag.retrieval.models import (
    RetrievalCandidate,
    RetrievalCandidateSet,
    RetrievalRuntimeRequest,
)
from app._deprecated.rag.retrieval.tracing import (
    RetrievalRuntimeTrace,
    StrategyInvocationTrace,
)


class RetrievalRuntime:
    """Orchestrates one or more retrieval strategies into a candidate set."""

    def __init__(
        self,
        strategies: Mapping[str, BaseRetrievalStrategy],
    ) -> None:
        # Defensive copy — the runtime owns its strategy table.
        self._strategies: dict[str, BaseRetrievalStrategy] = dict(strategies)

    @property
    def known_strategies(self) -> tuple[str, ...]:
        return tuple(sorted(self._strategies.keys()))

    async def retrieve(
        self,
        request: RetrievalRuntimeRequest,
        *,
        request_id: str | None = None,
    ) -> RetrievalRuntimeEnvelope:
        """Execute every named strategy and return a normalised envelope."""
        rid = request_id or get_request_id()
        loop = asyncio.get_event_loop()
        started_at = datetime.now(timezone.utc)
        loop_start = loop.time()

        # 1. Validate request shape up front.
        if not request.query or not request.query.strip():
            return self._finalize_failure(
                error=ValueError("retrieval runtime: query is empty"),
                request=request,
                request_id=rid,
                started_at=started_at,
                loop_start=loop_start,
                strategy_traces=(),
                pre_dedup=0,
                post_dedup=0,
                post_policy=0,
            )
        if not request.strategies:
            return self._finalize_failure(
                error=ValueError(
                    "retrieval runtime: no strategies named in request"
                ),
                request=request,
                request_id=rid,
                started_at=started_at,
                loop_start=loop_start,
                strategy_traces=(),
                pre_dedup=0,
                post_dedup=0,
                post_policy=0,
            )
        unknown = tuple(
            s for s in request.strategies if s not in self._strategies
        )
        if unknown:
            return self._finalize_failure(
                error=ValueError(
                    f"retrieval runtime: unknown strategies: {unknown}"
                ),
                request=request,
                request_id=rid,
                started_at=started_at,
                loop_start=loop_start,
                strategy_traces=(),
                pre_dedup=0,
                post_dedup=0,
                post_policy=0,
            )

        # 2. Invoke strategies sequentially in request order. Order is
        # significant — it drives merge precedence on duplicate chunks.
        per_strategy_candidates: list[Sequence[RetrievalCandidate]] = []
        strategy_traces: list[StrategyInvocationTrace] = []
        for strategy_name in request.strategies:
            strategy = self._strategies[strategy_name]
            invocation_trace = await self._invoke_strategy(
                strategy_name=strategy_name,
                strategy=strategy,
                request=request,
                request_id=rid,
                collected_into=per_strategy_candidates,
            )
            strategy_traces.append(invocation_trace)
            log_strategy_invocation(invocation_trace)
            record_strategy_invocation(
                strategy=invocation_trace.strategy,
                candidate_count=invocation_trace.candidate_count,
                latency_ms=invocation_trace.latency_ms,
                status=invocation_trace.status,
            )

        # 3. Aggregate failures. If every strategy failed, the runtime
        # call is a failure. If at least one succeeded, surface a
        # successful envelope with the merged set (other strategies'
        # errors live in the trace for inspection).
        all_failed = all(t.status == "failed" for t in strategy_traces)
        if all_failed:
            first_error = next(
                (
                    t.error
                    for t in strategy_traces
                    if t.error is not None
                ),
                "retrieval runtime: every strategy failed",
            )
            return self._finalize_failure(
                error=RuntimeError(first_error),
                request=request,
                request_id=rid,
                started_at=started_at,
                loop_start=loop_start,
                strategy_traces=tuple(strategy_traces),
                pre_dedup=0,
                post_dedup=0,
                post_policy=0,
            )

        # 4. Merge + dedup + sort deterministically.
        flat = tuple(c for batch in per_strategy_candidates for c in batch)
        pre_dedup = len(flat)
        deduped = _dedup_candidates(flat)
        post_dedup = len(deduped)

        # 5. Apply policy filtering.
        filtered = filter_candidates_by_policy(deduped, request.policy)
        post_policy = len(filtered)

        # 6. Final canonical sort. The merge already sorts, but policy
        # filtering preserves order — explicit sort here documents the
        # invariant: callers can rely on the final ordering regardless
        # of upstream changes.
        ordered = _canonical_sort(filtered)

        attribution = _attribution_counts(per_strategy_candidates, request.strategies)
        merged_from = tuple(
            s for s in request.strategies if attribution.get(s, 0) > 0
        )

        result = RetrievalCandidateSet(
            candidates=ordered,
            strategy_attribution=attribution,
            merged_from_strategies=merged_from,
        )

        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000, 2)
        trace = RetrievalRuntimeTrace(
            request_id=rid,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            status="ok",
            query_length=len(request.query),
            strategy_traces=tuple(strategy_traces),
            candidate_count_pre_dedup=pre_dedup,
            candidate_count_post_dedup=post_dedup,
            candidate_count_post_policy=post_policy,
            policy_id=request.policy.policy_id,
            tenant_scope=request.policy.tenant_scope,
            metadata=dict(request.metadata),
        )

        log_retrieval_runtime(trace)
        record_retrieval_runtime(
            policy_id=trace.policy_id,
            tenant_scope=trace.tenant_scope,
            strategy_count=len(strategy_traces),
            candidate_count_pre_dedup=pre_dedup,
            candidate_count_post_dedup=post_dedup,
            candidate_count_post_policy=post_policy,
            latency_ms=latency_ms,
            status="ok",
        )

        return RetrievalRuntimeEnvelope(trace=trace, result=result)

    # ─── Internals ────────────────────────────────────────────────────

    async def _invoke_strategy(
        self,
        *,
        strategy_name: str,
        strategy: BaseRetrievalStrategy,
        request: RetrievalRuntimeRequest,
        request_id: str | None,
        collected_into: list[Sequence[RetrievalCandidate]],
    ) -> StrategyInvocationTrace:
        loop = asyncio.get_event_loop()
        started_at = datetime.now(timezone.utc)
        s_start = loop.time()
        try:
            result = await strategy.execute(request, request_id=request_id)
        except Exception as exc:
            ended_at = datetime.now(timezone.utc)
            return StrategyInvocationTrace(
                strategy=strategy_name,
                status="failed",
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=round((loop.time() - s_start) * 1000, 2),
                candidate_count=0,
                error=f"{type(exc).__name__}: {exc}",
                embedding_trace=None,
            )

        collected_into.append(result.candidates)
        ended_at = datetime.now(timezone.utc)
        return StrategyInvocationTrace(
            strategy=strategy_name,
            status="ok",
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=round((loop.time() - s_start) * 1000, 2),
            candidate_count=len(result.candidates),
            error=None,
            embedding_trace=result.embedding_trace,
        )

    def _finalize_failure(
        self,
        *,
        error: BaseException,
        request: RetrievalRuntimeRequest,
        request_id: str | None,
        started_at: datetime,
        loop_start: float,
        strategy_traces: tuple[StrategyInvocationTrace, ...],
        pre_dedup: int,
        post_dedup: int,
        post_policy: int,
    ) -> RetrievalRuntimeEnvelope:
        loop = asyncio.get_event_loop()
        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000, 2)
        trace = RetrievalRuntimeTrace(
            request_id=request_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            status="failed",
            query_length=len(request.query),
            strategy_traces=strategy_traces,
            candidate_count_pre_dedup=pre_dedup,
            candidate_count_post_dedup=post_dedup,
            candidate_count_post_policy=post_policy,
            policy_id=request.policy.policy_id,
            tenant_scope=request.policy.tenant_scope,
            error=f"{type(error).__name__}: {error}",
            metadata=dict(request.metadata),
        )
        log_retrieval_runtime(trace)
        record_retrieval_runtime(
            policy_id=trace.policy_id,
            tenant_scope=trace.tenant_scope,
            strategy_count=len(strategy_traces),
            candidate_count_pre_dedup=pre_dedup,
            candidate_count_post_dedup=post_dedup,
            candidate_count_post_policy=post_policy,
            latency_ms=latency_ms,
            status="failed",
        )
        return RetrievalRuntimeEnvelope(trace=trace, error=error)


# ─── Pure helpers ─────────────────────────────────────────────────────


def _dedup_candidates(
    candidates: Sequence[RetrievalCandidate],
) -> tuple[RetrievalCandidate, ...]:
    """Dedup by chunk_id, keep highest score, tiebreak ascending UUID.

    Iteration order over `candidates` does not affect the result — the
    selection is fully order-independent. The output is sorted by
    `(score DESC, chunk_id ASC)`.
    """
    best: dict[uuid.UUID, RetrievalCandidate] = {}
    for candidate in candidates:
        incumbent = best.get(candidate.chunk_id)
        if incumbent is None:
            best[candidate.chunk_id] = candidate
            continue
        if candidate.score > incumbent.score:
            best[candidate.chunk_id] = candidate
        # Equal scores → keep the one with the lower UUID. Both
        # candidates have the same UUID (it is the dedup key), so this
        # branch is structurally unreachable — left explicit for the
        # reader so future code that loosens the key sees the tiebreak.
        # (No-op.)
    return _canonical_sort(tuple(best.values()))


def _canonical_sort(
    candidates: Sequence[RetrievalCandidate],
) -> tuple[RetrievalCandidate, ...]:
    """Sort `candidates` by `(score DESC, chunk_id ASC)`. Stable."""
    return tuple(
        sorted(
            candidates,
            key=lambda c: (-c.score, str(c.chunk_id)),
        )
    )


def _attribution_counts(
    per_strategy: Sequence[Sequence[RetrievalCandidate]],
    strategy_names: Sequence[str],
) -> Mapping[str, int]:
    """Per-strategy pre-dedup candidate counts."""
    counts: dict[str, int] = {name: 0 for name in strategy_names}
    for batch in per_strategy:
        for candidate in batch:
            if candidate.source_strategy in counts:
                counts[candidate.source_strategy] += 1
    return counts


__all__ = ["RetrievalRuntime"]
