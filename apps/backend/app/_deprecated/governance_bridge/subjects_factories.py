"""Subject factories — the bounded RAG-to-governance translation layer.

This module is the ONLY place in `app/governance/subjects/` that
imports Sprint H operational types (`AssemblyRequest`,
`AssembledContext`, etc.). The factories convert live operational
objects into typed governance subjects.

Architectural purpose:

* keep typed-subject construction in one bounded location,
* keep the subject value objects free of Sprint H imports (so the
  vocabulary is reusable for replay tools / persistence consumers
  that may not have Sprint H available),
* preserve the dependency-audit invariant that the rest of
  `app/governance/subjects/*` is import-clean.

Why the factories are pure functions, not adapter classes:

* deterministic by construction,
* trivially testable,
* no state, no surprise side-effects,
* easy to swap in alternate factories per stage (e.g. a
  POST_RETRIEVAL factory once that hook lands).
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from app.governance.subjects.execution import ExecutionGovernanceSubject
from app.governance.subjects.retrieval import (
    CandidateSummary,
    RetrievalGovernanceSubject,
)
from app._deprecated.rag.assembly.models import AssembledContext, AssemblyRequest
from app._deprecated.rag.retrieval.models import RetrievalCandidate


def retrieval_subject_for_assembly(
    request: AssemblyRequest,
    *,
    tenant_id: str | None,
    request_id: str | None,
    metadata: Mapping[str, Any] | None = None,
) -> RetrievalGovernanceSubject:
    """Build a PRE_RETRIEVAL governance subject from an `AssemblyRequest`.

    Used by `GovernedAssemblyRuntime` at the PRE_RETRIEVAL stage —
    candidates are empty because retrieval hasn't run yet.
    `candidate_count` and `estimated_tokens` are zero for the same
    reason; policies that care about these inspect the EXECUTION
    subject instead.
    """
    return RetrievalGovernanceSubject(
        query=request.query,
        tenant_id=tenant_id,
        policy_id=(
            request.policy.policy_id if request.policy is not None else None
        ),
        request_id=request_id,
        candidate_count=0,
        estimated_tokens=0,
        retrieval_candidates=(),
        metadata=dict(metadata or {}),
    )


def retrieval_subject_for_candidates(
    *,
    query: str,
    candidates: Sequence[RetrievalCandidate],
    tenant_id: str | None,
    policy_id: str | None,
    request_id: str | None,
    metadata: Mapping[str, Any] | None = None,
) -> RetrievalGovernanceSubject:
    """Build a POST_RETRIEVAL governance subject from live candidates.

    Currently unused by `GovernedAssemblyRuntime` (POST_RETRIEVAL
    integration is deferred to a future sprint). Shipped now so the
    contract exists; the future integration is a pure wiring change.
    """
    summaries = tuple(
        CandidateSummary(
            chunk_id=str(c.chunk_id),
            document_id=str(c.document_id) if c.document_id else None,
            score=c.score,
            content=c.content,
            source=c.source,
            source_strategy=c.source_strategy,
        )
        for c in candidates
    )
    return RetrievalGovernanceSubject(
        query=query,
        tenant_id=tenant_id,
        policy_id=policy_id,
        request_id=request_id,
        candidate_count=len(summaries),
        estimated_tokens=0,
        retrieval_candidates=summaries,
        metadata=dict(metadata or {}),
    )


def execution_subject_for_assembled_context(
    context: AssembledContext,
    *,
    tenant_id: str | None,
    request_id: str | None,
    execution_action: str = "rag.assemble_context.pre_execution",
    downstream_targets: tuple[str, ...] = (),
    metadata: Mapping[str, Any] | None = None,
) -> ExecutionGovernanceSubject:
    """Build a PRE_EXECUTION governance subject from an `AssembledContext`.

    Used by `GovernedAssemblyRuntime` after Sprint H assembly
    succeeds, before downstream consumers (future AI calls, agent
    actions) use the result. `downstream_targets` is supplied by
    callers that know the destination; empty tuple means "destination
    is unspecified at this hop".
    """
    return ExecutionGovernanceSubject(
        query=context.query,
        tenant_id=tenant_id,
        request_id=request_id,
        execution_action=execution_action,
        downstream_targets=downstream_targets,
        citation_count=context.citation_count,
        fragment_count=context.fragment_count,
        candidate_count_included=context.budgeting.included_count,
        estimated_tokens=context.budgeting.total_tokens,
        grounding_strategy=context.grounding.strategy_name,
        metadata=dict(metadata or {}),
    )


__all__ = [
    "retrieval_subject_for_assembly",
    "retrieval_subject_for_candidates",
    "execution_subject_for_assembled_context",
]
