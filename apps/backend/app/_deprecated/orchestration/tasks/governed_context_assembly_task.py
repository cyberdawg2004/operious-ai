"""Governed context-assembly orchestration task.

Thin adapter between the orchestration runtime and
`GovernedAssemblyRuntime`. Mirrors `ContextAssemblyTask` shape; the
distinguishing field on the payload is `tenant_id` (and optional
governance metadata). The orchestration result distinguishes three
failure modes via `TaskExecutionError`'s `__cause__`:

* governance evaluation failed (substrate failure),
* governance blocked execution (`GovernanceViolationError`),
* assembly failed (context-envelope failure).

Payload shape:

    {
        "query": str,                                # required
        "tenant_id": str | None,
        "actor": str | None,                          # defaults to "system"
        "top_k", "min_score", ...                    # standard assembly overrides
        "metadata": dict | None,
    }

Result `output` shape: JSON-serialisable summary of the assembled
context (citations, fragments) PLUS the governance decisions for
PRE_RETRIEVAL and PRE_EXECUTION.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Mapping

from app.governance.exceptions import GovernanceViolationError
from app._deprecated.governance_bridge.guardrails.adapters import (
    GovernedAssemblyRequest,
    GovernedAssemblyRuntime,
)
from app._deprecated.orchestration.context import TaskContext
from app._deprecated.orchestration.exceptions import TaskExecutionError
from app._deprecated.orchestration.models import TaskResult
from app._deprecated.orchestration.tasks.base import BaseTask
from app._deprecated.orchestration.tasks.context_assembly_task import (
    _serialize_assembled_context,
)
from app._deprecated.rag.assembly.models import AssemblyRequest
from app._deprecated.rag.budgeting.models import BudgetConstraint
from app._deprecated.rag.policies.models import RetrievalPolicy


class GovernedContextAssemblyTask(BaseTask):
    """Run governed context assembly via `GovernedAssemblyRuntime`."""

    name = "governance.assemble_context"

    def __init__(self, runtime: GovernedAssemblyRuntime) -> None:
        self._runtime = runtime

    async def execute(
        self,
        payload: Mapping[str, Any],
        context: TaskContext,
    ) -> TaskResult:
        try:
            query = payload["query"]
        except KeyError as exc:
            raise TaskExecutionError(
                f"governance.assemble_context: missing required field {exc}"
            ) from exc

        # Reuse the same policy/budget override builders as the
        # ungoverned task; identical request shape, only the actor /
        # tenant routing differs.
        policy = _policy_override(payload, runtime=self._runtime)
        budget = _budget_override(payload, runtime=self._runtime)

        metadata = dict(payload.get("metadata") or {})
        metadata.setdefault(
            "workflow_execution_id",
            str(context.orchestration.workflow_execution_id),
        )
        metadata.setdefault(
            "task_execution_id",
            str(context.task_execution_id),
        )

        request = GovernedAssemblyRequest(
            assembly=AssemblyRequest(
                query=query,
                policy=policy,
                budget=budget,
                strategies=_strategies_override(payload),
                reranker=payload.get("reranker"),
                grounding_strategy=payload.get("grounding_strategy"),
                metadata=metadata,
            ),
            tenant_id=payload.get("tenant_id"),
            actor=payload.get("actor") or "system",
            metadata=metadata,
        )

        envelope = await self._runtime.assemble(
            request,
            request_id=context.orchestration.request_id,
        )

        if not envelope.is_ok or envelope.result is None:
            cause = envelope.error
            err_label = type(cause).__name__ if cause else "unknown"
            raise TaskExecutionError(
                f"governance.assemble_context: failed at "
                f"{envelope.failed_stage or 'unknown'} ({err_label})"
            ) from cause

        result = envelope.result
        decisions_payload = {
            "pre_retrieval": _serialize_decision(result.pre_retrieval_decision),
            "pre_execution": _serialize_decision(result.pre_execution_decision),
        }
        return TaskResult(
            output={
                "context": _serialize_assembled_context(result.context),
                "governance": decisions_payload,
            },
            metadata={
                "pre_retrieval_decision": result.pre_retrieval_decision.decision.value,
                "pre_execution_decision": result.pre_execution_decision.decision.value,
                "pre_retrieval_violation_count": len(
                    result.pre_retrieval_decision.violations
                ),
                "pre_execution_violation_count": len(
                    result.pre_execution_decision.violations
                ),
                "restriction_count": len(result.restrictions),
            },
        )


# ─── Override builders ────────────────────────────────────────────────


def _policy_override(
    payload: Mapping[str, Any],
    *,
    runtime: GovernedAssemblyRuntime,
) -> RetrievalPolicy | None:
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
    # Pull the underlying assembly service's defaults so partial
    # overrides preserve the rest of the policy shape.
    base = runtime._assembly.default_policy  # noqa: SLF001  — intentional read
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
    payload: Mapping[str, Any],
    *,
    runtime: GovernedAssemblyRuntime,
) -> BudgetConstraint | None:
    keys = ("max_tokens", "max_chunks", "max_chunks_per_doc")
    if not any(k in payload for k in keys):
        return None
    base = runtime._assembly.default_budget  # noqa: SLF001
    return dataclasses.replace(
        base,
        max_tokens=payload.get("max_tokens", base.max_tokens),
        max_chunks=payload.get("max_chunks", base.max_chunks),
        max_chunks_per_doc=payload.get(
            "max_chunks_per_doc", base.max_chunks_per_doc
        ),
    )


def _strategies_override(payload: Mapping[str, Any]) -> tuple[str, ...] | None:
    raw = payload.get("strategies")
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)):
        raise TaskExecutionError(
            "governance.assemble_context: `strategies` must be a list or tuple"
        )
    return tuple(str(s) for s in raw)


def _serialize_decision(decision) -> dict[str, Any]:
    return {
        "decision_id": str(decision.decision_id),
        "decision": decision.decision.value,
        "stage": decision.stage.value,
        "policy_chain_id": decision.policy_chain_id,
        "reason": decision.reason,
        "rule_count": len(decision.evaluated_rules),
        "violation_count": len(decision.violations),
        "restriction_count": len(decision.restrictions),
        "violations": [
            {
                "policy_name": v.policy_name,
                "rule_id": v.rule_id,
                "decision": v.decision.value,
                "severity": int(v.severity),
                "detail": v.detail,
            }
            for v in decision.violations
        ],
        "restrictions": [
            {
                "kind": r.kind.value,
                "target": r.target,
                "value": r.value,
                "policy_name": r.policy_name,
                "rule_id": r.rule_id,
            }
            for r in decision.restrictions
        ],
    }


__all__ = ["GovernedContextAssemblyTask"]
