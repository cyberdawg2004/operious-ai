"""Retrieval governance subject — canonical input for retrieval-stage policies.

Used at `EnforcementStage.PRE_RETRIEVAL` and (when wired) at
`EnforcementStage.POST_RETRIEVAL`. Carries the request-shape
information policies need WITHOUT importing any retrieval-runtime
types — the small `CandidateSummary` value object is the only shape
that crosses into governance.

Why a summary, not a runtime candidate object:

* The substrate is a leaf in the dependency graph (enforced by the
  dependency audit). Importing a retrieval runtime type here would
  couple governance to that runtime.
* Governance only needs `chunk_id` + `content` + `score` + `source`
  for content-based policies; full runtime candidate objects carry
  more than needed and include UUID objects that are awkward to
  serialize.
* Subjects are built by the *composing* runtime — the caller that
  owns both the retrieval surface and the governance call — so the
  coupling is concentrated at one composition boundary, never inside
  the governance substrate.

Phase 2.1 quarantine note: the prior `app/governance/subjects/
factories.py` translation layer was quarantined under
`app/_deprecated/governance_bridge/` together with the legacy
RAG / assembly pipeline. Subjects are now built directly by the
composition root that invokes governance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.governance.subjects.base import BaseGovernanceSubject, SubjectKind
from app.types.json import JsonObject


def _empty_json_object() -> JsonObject:
    return {}


@dataclass(frozen=True, slots=True)
class CandidateSummary:
    """Compact summary of one retrieval candidate for governance.

    String-keyed identifiers (not UUID) so the value object is
    trivially JSON-serializable and immune to UUID-vs-string
    confusion. The factory layer converts UUIDs to strings.
    """

    chunk_id: str
    document_id: str | None
    score: float
    content: str
    source: str | None = None
    source_strategy: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "score": self.score,
            "content": self.content,
            "source": self.source,
            "source_strategy": self.source_strategy,
        }


@dataclass(frozen=True, slots=True)
class RetrievalGovernanceSubject(BaseGovernanceSubject):
    """Canonical retrieval-stage governance subject.

    All fields are operationally meaningful; metadata is for
    cross-cutting context that doesn't fit a typed slot.

    Attributes:
        query:                 The request's natural-language query.
        tenant_id:             Tenant scope (None for global / dev).
        policy_id:             RAG-level `RetrievalPolicy.policy_id`
                               (Sprint H concept) the request will use.
                               Note: this is NOT the governance policy
                               chain id — they are different layers.
        request_id:            Platform-wide request lineage id.
        candidate_count:       Cardinality of the candidate set; for
                               POST_RETRIEVAL governance this is the
                               *retrieved* count (pre-filter).
        estimated_tokens:      Heuristic estimate, useful for cost /
                               budget governance.
        retrieval_candidates:  Per-candidate summaries (empty at
                               PRE_RETRIEVAL; populated at
                               POST_RETRIEVAL when that hook lands).
        metadata:              Free-form structured payload.
    """

    query: str = ""
    tenant_id: str | None = None
    policy_id: str | None = None
    request_id: str | None = None
    candidate_count: int = 0
    estimated_tokens: int = 0
    retrieval_candidates: tuple[CandidateSummary, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=_empty_json_object)
    kind: SubjectKind = SubjectKind.RETRIEVAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "query": self.query,
            "tenant_id": self.tenant_id,
            "policy_id": self.policy_id,
            "request_id": self.request_id,
            "candidate_count": self.candidate_count,
            "estimated_tokens": self.estimated_tokens,
            "retrieval_candidates": [c.to_dict() for c in self.retrieval_candidates],
            "metadata": dict(self.metadata),
        }


__all__ = ["RetrievalGovernanceSubject", "CandidateSummary"]
