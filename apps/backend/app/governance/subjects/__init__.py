"""Typed governance subjects.

Sprint I Hardening introduces typed, discriminated subjects to
replace the loose `subject: Mapping[str, Any]` contract of Sprint I.

Subjects are the **typed evaluation input** every policy reads. Each
subject is:

* `@dataclass(frozen=True, slots=True)` — immutable, replay-safe,
* discriminated by a `SubjectKind` enum,
* serializable via `to_dict()` (used by persistence layer),
* operationally meaningful — fields match the stage they target.

Layout:

* `base`            — `BaseGovernanceSubject`, `SubjectKind`,
                      `GenericGovernanceSubject` (legacy fallback).
* `retrieval`       — `RetrievalGovernanceSubject`, `CandidateSummary`.
* `execution`       — `ExecutionGovernanceSubject`.
* `agent_actions`   — `AgentActionGovernanceSubject` (stub for Sprint J/L).
* `communication`   — `CommunicationGovernanceSubject`,
                      `AttachmentSummary` (stub for comms runtime).

Subjects do NOT reference Sprint H runtime types. They reference
small value-object summaries (`CandidateSummary`, `AttachmentSummary`)
that callers build from operational inputs. This keeps the
governance substrate a leaf in the dependency graph.

Phase 2.1 quarantine note:

* `factories.py` (legacy RAG → typed subject adapter) was moved under
  `app/_deprecated/governance_bridge/subjects_factories.py` because
  it imported from `app.rag.assembly` / `app.rag.retrieval`. Its
  surface is no longer part of the constitutional governance
  substrate.
"""

from app.governance.subjects.agent_actions import AgentActionGovernanceSubject
from app.governance.subjects.base import (
    BaseGovernanceSubject,
    GenericGovernanceSubject,
    SubjectKind,
)
from app.governance.subjects.communication import (
    AttachmentSummary,
    CommunicationGovernanceSubject,
)
from app.governance.subjects.execution import ExecutionGovernanceSubject
from app.governance.subjects.retrieval import (
    CandidateSummary,
    RetrievalGovernanceSubject,
)

__all__ = [
    "BaseGovernanceSubject",
    "SubjectKind",
    "GenericGovernanceSubject",
    "RetrievalGovernanceSubject",
    "CandidateSummary",
    "ExecutionGovernanceSubject",
    "AgentActionGovernanceSubject",
    "CommunicationGovernanceSubject",
    "AttachmentSummary",
]
