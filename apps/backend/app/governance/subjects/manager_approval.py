"""Manager approval governance subject."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping

from app.governance.subjects.base import BaseGovernanceSubject, SubjectKind
from app.types.json import JsonObject


def _empty_json_object() -> JsonObject:
    return {}


@dataclass(frozen=True, slots=True)
class ManagerApprovalGovernanceSubject(BaseGovernanceSubject):
    """Human manager approval lineage for explicitly persisted decisions."""

    subject_kind: ClassVar[str] = "manager_approval"

    tool_name: str
    action_approval_id: str
    original_governance_decision_id: str
    approved_by: str
    session_id: str
    tenant_id: str
    metadata: Mapping[str, Any] = field(default_factory=_empty_json_object)
    kind: SubjectKind = SubjectKind.MANAGER_APPROVAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "subject_kind": self.subject_kind,
            "tool_name": self.tool_name,
            "action_approval_id": self.action_approval_id,
            "original_governance_decision_id": (
                self.original_governance_decision_id
            ),
            "approved_by": self.approved_by,
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "metadata": dict(self.metadata),
        }


__all__ = ["ManagerApprovalGovernanceSubject"]
