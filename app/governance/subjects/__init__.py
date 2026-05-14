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
* `factories`       — adapters that build typed subjects from
                      Sprint H operational types WITHOUT importing
                      runtime modules at module load time.

Subjects do NOT reference Sprint H runtime types. They reference
small value-object summaries (`CandidateSummary`, `AttachmentSummary`)
that the factories build from operational inputs. This keeps the
governance substrate a leaf in the dependency graph.
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
