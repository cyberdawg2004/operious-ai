"""Context assembly orchestration task.

Thin adapter between the orchestration runtime and
`ContextAssemblyService`. The assembly service never raises (always
returns a `ContextEnvelope`), so this task translates envelope outcomes
into the orchestration vocabulary:

* `envelope.is_ok` → `TaskResult` carrying the serialised assembled
  context;
* `envelope.error` → `TaskExecutionError` (runtime converts to
  `TaskEnvelope(error=...)`).

Payload shape (all optional except `query`):
    {
        "query": str,                                # required
        "top_k": int | None,                          # overrides default policy
        "min_score": float | None,
        "metadata_filter": dict | None,
        "max_tokens": int | None,                     # overrides default budget
        "max_chunks_per_doc": int | None,
        "strategies": list[str] | None,               # retrieval strategies
        "reranker": str | None,
        "grounding_strategy": str | None,
        "policy_id": str | None,
        "tenant_scope": str | None,
        "metadata": dict | None,
    }

Result `output` shape: JSON-serialisable summary of the
`AssembledContext` (citations, fragments, budgeting decisions). The
full envelope is not serialised — the operational view is the citation
+ fragment list with stage counters.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Mapping

from app.orchestration.context import TaskContext
from app.orchestration.exceptions import TaskExecutionError
from app.orchestration.models import TaskResult
from app.orchestration.tasks.base import BaseTask
from app.rag.assembly.models import AssembledContext, AssemblyRequest
from app.rag.assembly.service import ContextAssemblyService
from app.rag.budgeting.models import BudgetConstraint
from app.rag.policies.models import RetrievalPolicy


class ContextAssemblyTask(BaseTask):
    """Run one context assembly via `ContextAssemblyService`."""

    name = "rag.assemble_context"

    def __init__(self, assembly_service: ContextAssemblyService) -> None:
        self._service = assembly_service

    async def execute(
        self,
        payload: Mapping[str, Any],
        context: TaskContext,
    ) -> TaskResult:
        try:
            query = payload["query"]
        except KeyError as exc:
            raise TaskExecutionError(
                f"rag.assemble_context: missing required field {exc}"
            ) from exc

        # Build optional overrides — only present when the caller passed
        # them. Falling back to the service's DI defaults otherwise.
        policy = self._policy_override(payload)
        budget = self._budget_override(payload)
        strategies = self._strategies_override(payload)
        reranker = payload.get("reranker")
        grounding_strategy = payload.get("grounding_strategy")

        metadata = dict(payload.get("metadata") or {})
        metadata.setdefault(
            "workflow_execution_id",
            str(context.orchestration.workflow_execution_id),
        )
        metadata.setdefault(
            "task_execution_id",
            str(context.task_execution_id),
        )
        metadata.setdefault(
            "workflow_name",
            context.orchestration.workflow_name,
        )

        envelope = await self._service.assemble(
            AssemblyRequest(
                query=query,
                policy=policy,
                budget=budget,
                strategies=strategies,
                reranker=reranker,
                grounding_strategy=grounding_strategy,
                metadata=metadata,
            ),
            request_id=context.orchestration.request_id,
        )

        if not envelope.is_ok or envelope.result is None:
            err_name = (
                type(envelope.error).__name__ if envelope.error else "unknown"
            )
            raise TaskExecutionError(
                f"rag.assemble_context: assembly failed at "
                f"{envelope.trace.failed_stage or 'unknown'} ({err_name})"
            ) from envelope.error

        assembled = envelope.result
        return TaskResult(
            output=_serialize_assembled_context(assembled),
            metadata={
                "candidate_count_post_retrieval": (
                    envelope.trace.candidate_count_post_retrieval
                ),
                "candidate_count_post_rerank": (
                    envelope.trace.candidate_count_post_rerank
                ),
                "candidate_count_included": envelope.trace.candidate_count_included,
                "candidate_count_excluded": envelope.trace.candidate_count_excluded,
                "citation_count": envelope.trace.citation_count,
                "fragment_count": envelope.trace.fragment_count,
                "estimated_tokens": envelope.trace.estimated_tokens,
                "reranker_name": envelope.trace.reranker_name,
                "grounding_strategy": envelope.trace.grounding_strategy,
                "latency_ms": envelope.trace.latency_ms,
            },
        )

    # ─── Override builders ───────────────────────────────────────────

    def _policy_override(
        self,
        payload: Mapping[str, Any],
    ) -> RetrievalPolicy | None:
        """Build a policy override if any policy field is in the payload."""
        keys = (
            "top_k",
            "min_score",
            "max_chunks_per_doc",
            "metadata_filter",
            "policy_id",
            "tenant_scope",
        )
        if not any(k in payload for k in keys):
            return None
        base = self._service.default_policy
        return dataclasses.replace(
            base,
            top_k=int(payload.get("top_k", base.top_k)),
            min_score=payload.get("min_score", base.min_score),
            max_chunks_per_doc=payload.get(
                "max_chunks_per_doc", base.max_chunks_per_doc
            ),
            metadata_filter=dict(
                payload.get("metadata_filter") or base.metadata_filter
            ),
            policy_id=payload.get("policy_id", base.policy_id),
            tenant_scope=payload.get("tenant_scope", base.tenant_scope),
        )

    def _budget_override(
        self,
        payload: Mapping[str, Any],
    ) -> BudgetConstraint | None:
        """Build a budget override if any budget field is in the payload."""
        keys = ("max_tokens", "max_chunks", "max_chunks_per_doc")
        if not any(k in payload for k in keys):
            return None
        base = self._service.default_budget
        return dataclasses.replace(
            base,
            max_tokens=payload.get("max_tokens", base.max_tokens),
            max_chunks=payload.get("max_chunks", base.max_chunks),
            max_chunks_per_doc=payload.get(
                "max_chunks_per_doc", base.max_chunks_per_doc
            ),
        )

    @staticmethod
    def _strategies_override(
        payload: Mapping[str, Any],
    ) -> tuple[str, ...] | None:
        raw = payload.get("strategies")
        if raw is None:
            return None
        if not isinstance(raw, (list, tuple)):
            raise TaskExecutionError(
                "rag.assemble_context: `strategies` must be a list or tuple"
            )
        return tuple(str(s) for s in raw)


def _serialize_assembled_context(ctx: AssembledContext) -> dict[str, Any]:
    """JSON-serialisable view of an `AssembledContext`."""
    return {
        "query": ctx.query,
        "reranker_name": ctx.reranker_name,
        "grounding_strategy": ctx.grounding_strategy,
        "citation_count": ctx.citation_count,
        "fragment_count": ctx.fragment_count,
        "citations": [
            {
                "index": c.index,
                "chunk_id": str(c.chunk_id),
                "document_id": str(c.document_id),
                "ordinal": c.ordinal,
                "score": c.score,
                "source": c.source,
                "source_strategy": c.source_strategy,
                "metadata": dict(c.metadata),
            }
            for c in ctx.citation_index
        ],
        "fragments": [
            {
                "citation_index": f.citation_index,
                "chunk_id": str(f.chunk_id),
                "document_id": str(f.document_id),
                "content": f.content,
                "score": f.score,
                "metadata": dict(f.metadata),
            }
            for f in ctx.grounding
        ],
        "budgeting": {
            "total_tokens": ctx.budgeting.total_tokens,
            "included_count": ctx.budgeting.included_count,
            "excluded_count": ctx.budgeting.excluded_count,
            "decisions": [
                {
                    "chunk_id": str(d.candidate.chunk_id),
                    "reason": d.reason.value,
                    "estimated_tokens": d.estimated_tokens,
                }
                for d in ctx.budgeting.decisions
            ],
        },
        "retrieval": {
            "candidate_count": len(ctx.retrieval_candidates),
            "strategy_attribution": dict(
                ctx.retrieval_candidates.strategy_attribution
            ),
            "merged_from_strategies": list(
                ctx.retrieval_candidates.merged_from_strategies
            ),
        },
        "metadata": dict(ctx.metadata),
    }


__all__ = ["ContextAssemblyTask"]
