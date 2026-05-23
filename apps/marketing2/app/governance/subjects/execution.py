"""Execution governance subject — canonical input for execution-stage policies.

Used at `EnforcementStage.PRE_EXECUTION` and (future)
`EnforcementStage.POST_EXECUTION`. Represents the assembled state
about to be consumed by a downstream operational target (an AI call,
an agent action, an export).

Same architectural discipline as the retrieval subject: it carries
small summaries / typed scalars only, NOT live Sprint H objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.governance.subjects.base import BaseGovernanceSubject, SubjectKind


@dataclass(frozen=True, slots=True)
class ExecutionGovernanceSubject(BaseGovernanceSubject):
    """Canonical execution-stage governance subject.

    Attributes:
        query:                       Original request query (for
                                     correlation with PRE_RETRIEVAL
                                     subject without joining traces).
        tenant_id:                   Tenant scope.
        request_id:                  Platform-wide request id.
        execution_action:            Stable, namespaced action string
                                     (e.g. "ai.completion",
                                     "agent.tool_invocation"). Mirrors
                                     the audit-event action vocabulary.
        downstream_targets:          Tuple of stable target identifiers
                                     the assembled state is destined
                                     for (e.g. "model:openai:gpt-4o",
                                     "agent:supervisor"). Empty when
                                     the destination is unspecified.
        citation_count:              How many citations are in the
                                     assembled context.
        fragment_count:              How many grounding fragments.
        candidate_count_included:    Budgeting-included candidate count.
        estimated_tokens:            Heuristic total token estimate of
                                     the assembled context.
        grounding_strategy:          Stable name of the grounding
                                     strategy used (e.g. "default").
        metadata:                    Free-form structured payload.
    """

    query: str = ""
    tenant_id: str | None = None
    request_id: str | None = None
    execution_action: str = ""
    downstream_targets: tuple[str, ...] = ()
    citation_count: int = 0
    fragment_count: int = 0
    candidate_count_included: int = 0
    estimated_tokens: int = 0
    grounding_strategy: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    kind: SubjectKind = SubjectKind.EXECUTION

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "query": self.query,
            "tenant_id": self.tenant_id,
            "request_id": self.request_id,
            "execution_action": self.execution_action,
            "downstream_targets": list(self.downstream_targets),
            "citation_count": self.citation_count,
            "fragment_count": self.fragment_count,
            "candidate_count_included": self.candidate_count_included,
            "estimated_tokens": self.estimated_tokens,
            "grounding_strategy": self.grounding_strategy,
            "metadata": dict(self.metadata),
        }


__all__ = ["ExecutionGovernanceSubject"]
