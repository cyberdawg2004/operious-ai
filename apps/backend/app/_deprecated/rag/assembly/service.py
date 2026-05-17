"""Context assembly service — Sprint H apex orchestrator.

One public method (`assemble`) runs the full pipeline:

    retrieval runtime → reranker → budgeting → citations → grounding

The service is **synchronous in pipeline structure**, **async at each
stage** (every stage that does I/O awaits). It never raises — every
outcome is wrapped in a `ContextEnvelope`.

Sub-envelopes (`RetrievalRuntimeEnvelope`, `RerankingEnvelope`) are
preserved on the final envelope so replayers can reconstruct lineage
without re-running the pipeline.

Determinism contract:

* retrieval is deterministic per Sprint G + per `RetrievalRuntime`
  contract,
* the reranker is deterministic per `BaseReranker` contract (the shipped
  `IdentityReranker` trivially so),
* budgeting is deterministic by construction,
* citation numbering is deterministic by construction,
* grounding assembly is deterministic by construction.

Replay implications: a saved `ContextEnvelope` carries every input
identifier (request_id, policy_id, tenant_scope) and every per-stage
sub-trace. Combined with deterministic vector + heuristic estimator,
the same envelope can be reconstructed bit-for-bit from the same
inputs.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import datetime, timezone
from typing import Mapping

from app.core.config import Settings
from app.observability.audit import AuditEvent, emit_audit_event
from app.observability.context import get_request_id
from app._deprecated.observability.context_assembly_logging import log_context_assembly
from app._deprecated.observability.context_assembly_metrics import record_context_assembly
from app._deprecated.rag.assembly.envelopes import ContextEnvelope
from app._deprecated.rag.assembly.models import AssembledContext, AssemblyRequest
from app._deprecated.rag.assembly.tracing import AssemblyTrace
from app._deprecated.rag.budgeting.estimator import BaseTokenEstimator
from app._deprecated.rag.budgeting.models import BudgetConstraint
from app._deprecated.rag.budgeting.service import apply_budget
from app._deprecated.rag.citations.builder import build_citation_index
from app._deprecated.rag.grounding.base import BaseGroundingStrategy
from app._deprecated.rag.policies.models import RetrievalPolicy
from app._deprecated.rag.reranking.envelopes import RerankingEnvelope
from app._deprecated.rag.reranking.models import RerankingRequest
from app._deprecated.rag.reranking.registry import RerankerRegistry
from app._deprecated.rag.retrieval.envelopes import RetrievalRuntimeEnvelope
from app._deprecated.rag.retrieval.models import RetrievalCandidateSet, RetrievalRuntimeRequest
from app._deprecated.rag.retrieval.runtime import RetrievalRuntime
from app.services.base import BaseService


class ContextAssemblyService(BaseService):
    """Sprint H apex orchestrator. Assembles deterministic, replayable context."""

    def __init__(
        self,
        *,
        retrieval_runtime: RetrievalRuntime,
        reranker_registry: RerankerRegistry,
        token_estimator: BaseTokenEstimator,
        grounding_strategies: Mapping[str, BaseGroundingStrategy],
        settings: Settings,
    ) -> None:
        super().__init__()
        self._retrieval_runtime = retrieval_runtime
        self._reranker_registry = reranker_registry
        self._token_estimator = token_estimator
        self._grounding_strategies: dict[str, BaseGroundingStrategy] = dict(
            grounding_strategies
        )
        self._settings = settings

        # Resolve and freeze DI-injected defaults once at construction
        # so per-request work does not re-touch settings.
        self._default_strategies: tuple[str, ...] = (
            settings.RAG_DEFAULT_RETRIEVAL_STRATEGY,
        )
        self._default_reranker_name = settings.RAG_DEFAULT_RERANKER
        self._default_grounding_strategy = settings.RAG_DEFAULT_GROUNDING_STRATEGY
        self._default_policy = RetrievalPolicy(
            top_k=settings.RAG_DEFAULT_TOP_K,
            min_score=(
                settings.RAG_DEFAULT_MIN_SCORE
                if settings.RAG_DEFAULT_MIN_SCORE > 0.0
                else None
            ),
            max_chunks_per_doc=settings.RAG_DEFAULT_MAX_CHUNKS_PER_DOCUMENT,
        )
        self._default_budget = BudgetConstraint(
            max_tokens=settings.RAG_DEFAULT_CONTEXT_TOKEN_BUDGET,
            max_chunks=None,
            max_chunks_per_doc=settings.RAG_DEFAULT_MAX_CHUNKS_PER_DOCUMENT,
            min_score=None,
            estimator_name=token_estimator.name,
        )

        # Validate that defaults are resolvable at construction time —
        # fail fast at boot, not on the first request.
        if not self._reranker_registry.has(self._default_reranker_name):
            raise RuntimeError(
                f"ContextAssemblyService: default reranker "
                f"{self._default_reranker_name!r} not registered."
            )
        if self._default_grounding_strategy not in self._grounding_strategies:
            raise RuntimeError(
                f"ContextAssemblyService: default grounding strategy "
                f"{self._default_grounding_strategy!r} not registered."
            )

    # ─── Public API ───────────────────────────────────────────────────

    async def assemble(
        self,
        request: AssemblyRequest,
        *,
        request_id: str | None = None,
    ) -> ContextEnvelope:
        """Execute the assembly pipeline. Never raises."""
        rid = request_id or get_request_id()
        loop = asyncio.get_event_loop()
        started_at = datetime.now(timezone.utc)
        loop_start = loop.time()

        # 0. Resolve effective configuration.
        policy = request.policy or self._default_policy
        budget = request.budget or self._default_budget
        if not budget.estimator_name:
            budget = dataclasses.replace(
                budget, estimator_name=self._token_estimator.name
            )
        strategies = request.strategies or self._default_strategies
        reranker_name = request.reranker or self._default_reranker_name
        grounding_strategy_name = (
            request.grounding_strategy or self._default_grounding_strategy
        )

        if not request.query or not request.query.strip():
            return self._finalize_failure(
                error=ValueError("assembly request: query is empty"),
                request=request,
                request_id=rid,
                started_at=started_at,
                loop_start=loop_start,
                failed_stage="validation",
                policy=policy,
                reranker_name=reranker_name,
                grounding_strategy=grounding_strategy_name,
            )

        # 1. Retrieval runtime.
        retrieval_envelope = await self._retrieval_runtime.retrieve(
            RetrievalRuntimeRequest(
                query=request.query,
                policy=policy,
                strategies=strategies,
                metadata=dict(request.metadata),
            ),
            request_id=rid,
        )
        if not retrieval_envelope.is_ok:
            return self._finalize_failure(
                error=retrieval_envelope.error or RuntimeError(
                    "retrieval runtime: no result"
                ),
                request=request,
                request_id=rid,
                started_at=started_at,
                loop_start=loop_start,
                failed_stage="retrieval",
                policy=policy,
                reranker_name=reranker_name,
                grounding_strategy=grounding_strategy_name,
                retrieval_envelope=retrieval_envelope,
            )
        candidate_set = retrieval_envelope.unwrap()

        # 2. Reranking.
        try:
            reranker = self._reranker_registry.get(reranker_name)
        except KeyError as exc:
            return self._finalize_failure(
                error=exc,
                request=request,
                request_id=rid,
                started_at=started_at,
                loop_start=loop_start,
                failed_stage="reranking",
                policy=policy,
                reranker_name=reranker_name,
                grounding_strategy=grounding_strategy_name,
                retrieval_envelope=retrieval_envelope,
            )

        reranking_envelope: RerankingEnvelope = await reranker.rerank(
            RerankingRequest(
                query=request.query,
                candidates=candidate_set.candidates,
                metadata=dict(request.metadata),
            ),
            request_id=rid,
        )
        if not reranking_envelope.is_ok:
            return self._finalize_failure(
                error=reranking_envelope.error or RuntimeError(
                    "reranking: no result"
                ),
                request=request,
                request_id=rid,
                started_at=started_at,
                loop_start=loop_start,
                failed_stage="reranking",
                policy=policy,
                reranker_name=reranker_name,
                grounding_strategy=grounding_strategy_name,
                retrieval_envelope=retrieval_envelope,
                reranking_envelope=reranking_envelope,
            )
        reranked = reranking_envelope.unwrap().candidates

        # 3. Budgeting.
        budgeting_result = apply_budget(
            reranked,
            budget,
            self._token_estimator,
        )

        # 4. Citation index.
        citation_index = build_citation_index(budgeting_result.included)

        # 5. Grounding.
        grounding_strategy = self._grounding_strategies.get(
            grounding_strategy_name
        )
        if grounding_strategy is None:
            return self._finalize_failure(
                error=KeyError(
                    f"unknown grounding strategy: {grounding_strategy_name!r}"
                ),
                request=request,
                request_id=rid,
                started_at=started_at,
                loop_start=loop_start,
                failed_stage="grounding",
                policy=policy,
                reranker_name=reranker_name,
                grounding_strategy=grounding_strategy_name,
                retrieval_envelope=retrieval_envelope,
                reranking_envelope=reranking_envelope,
            )

        grounding_result = grounding_strategy.build(
            budgeting_result.included,
            citation_index,
        )

        # 6. Compose final assembled context.
        assembled = AssembledContext(
            query=request.query,
            retrieval_candidates=candidate_set,
            budgeting=budgeting_result,
            citation_index=citation_index,
            grounding=grounding_result,
            reranker_name=reranker_name,
            grounding_strategy=grounding_strategy_name,
            metadata=dict(request.metadata),
        )

        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000, 2)
        trace = AssemblyTrace(
            request_id=rid,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            status="ok",
            query_length=len(request.query),
            strategy_count=len(retrieval_envelope.trace.strategy_traces),
            candidate_count_post_retrieval=len(candidate_set),
            candidate_count_post_rerank=len(reranked),
            candidate_count_included=budgeting_result.included_count,
            candidate_count_excluded=budgeting_result.excluded_count,
            citation_count=len(citation_index),
            fragment_count=len(grounding_result),
            estimated_tokens=budgeting_result.total_tokens,
            reranker_name=reranker_name,
            grounding_strategy=grounding_strategy_name,
            policy_id=policy.policy_id,
            tenant_scope=policy.tenant_scope,
            metadata=dict(request.metadata),
        )

        log_context_assembly(trace)
        record_context_assembly(
            policy_id=trace.policy_id,
            tenant_scope=trace.tenant_scope,
            reranker_name=trace.reranker_name,
            grounding_strategy=trace.grounding_strategy,
            candidate_count_post_retrieval=trace.candidate_count_post_retrieval,
            candidate_count_post_rerank=trace.candidate_count_post_rerank,
            candidate_count_included=trace.candidate_count_included,
            candidate_count_excluded=trace.candidate_count_excluded,
            citation_count=trace.citation_count,
            fragment_count=trace.fragment_count,
            estimated_tokens=trace.estimated_tokens,
            latency_ms=latency_ms,
            status="ok",
        )
        emit_audit_event(
            AuditEvent(
                actor="context_assembly_service",
                action="rag.assemble_context",
                resource=(
                    f"policy:{policy.policy_id or 'default'}/"
                    f"tenant:{policy.tenant_scope or 'global'}"
                ),
                metadata={
                    "citation_count": trace.citation_count,
                    "fragment_count": trace.fragment_count,
                    "estimated_tokens": trace.estimated_tokens,
                    "candidate_count_included": trace.candidate_count_included,
                    "candidate_count_excluded": trace.candidate_count_excluded,
                    "latency_ms": latency_ms,
                    "reranker_name": reranker_name,
                    "grounding_strategy": grounding_strategy_name,
                },
                request_id=rid,
            )
        )

        return ContextEnvelope(
            trace=trace,
            result=assembled,
            retrieval_envelope=retrieval_envelope,
            reranking_envelope=reranking_envelope,
        )

    # ─── Inspection helpers (read-only) ──────────────────────────────

    @property
    def default_policy(self) -> RetrievalPolicy:
        return self._default_policy

    @property
    def default_budget(self) -> BudgetConstraint:
        return self._default_budget

    # ─── Internals ────────────────────────────────────────────────────

    def _finalize_failure(
        self,
        *,
        error: BaseException,
        request: AssemblyRequest,
        request_id: str | None,
        started_at: datetime,
        loop_start: float,
        failed_stage: str,
        policy: RetrievalPolicy,
        reranker_name: str | None,
        grounding_strategy: str | None,
        retrieval_envelope: RetrievalRuntimeEnvelope | None = None,
        reranking_envelope: RerankingEnvelope | None = None,
    ) -> ContextEnvelope:
        loop = asyncio.get_event_loop()
        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000, 2)

        post_retrieval = (
            len(retrieval_envelope.result)
            if retrieval_envelope and retrieval_envelope.is_ok
            and retrieval_envelope.result is not None
            else 0
        )
        post_rerank = (
            reranking_envelope.result.output_count
            if reranking_envelope and reranking_envelope.is_ok
            and reranking_envelope.result is not None
            else 0
        )

        trace = AssemblyTrace(
            request_id=request_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            status="failed",
            query_length=len(request.query),
            strategy_count=(
                len(retrieval_envelope.trace.strategy_traces)
                if retrieval_envelope
                else 0
            ),
            candidate_count_post_retrieval=post_retrieval,
            candidate_count_post_rerank=post_rerank,
            candidate_count_included=0,
            candidate_count_excluded=0,
            citation_count=0,
            fragment_count=0,
            estimated_tokens=0,
            reranker_name=reranker_name,
            grounding_strategy=grounding_strategy,
            policy_id=policy.policy_id,
            tenant_scope=policy.tenant_scope,
            error=f"{type(error).__name__}: {error}",
            failed_stage=failed_stage,
            metadata=dict(request.metadata),
        )
        log_context_assembly(trace)
        record_context_assembly(
            policy_id=trace.policy_id,
            tenant_scope=trace.tenant_scope,
            reranker_name=trace.reranker_name,
            grounding_strategy=trace.grounding_strategy,
            candidate_count_post_retrieval=post_retrieval,
            candidate_count_post_rerank=post_rerank,
            candidate_count_included=0,
            candidate_count_excluded=0,
            citation_count=0,
            fragment_count=0,
            estimated_tokens=0,
            latency_ms=latency_ms,
            status="failed",
        )
        return ContextEnvelope(
            trace=trace,
            error=error,
            retrieval_envelope=retrieval_envelope,
            reranking_envelope=reranking_envelope,
        )


__all__ = ["ContextAssemblyService"]
