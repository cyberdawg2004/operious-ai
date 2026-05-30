"""Cluster governance subject for defect-report synthesis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping

from app.governance.subjects.base import BaseGovernanceSubject, SubjectKind
from app.types.json import JsonObject


def _empty_json_object() -> JsonObject:
    return {}


@dataclass(frozen=True, slots=True)
class ClusterGovernanceSubject(BaseGovernanceSubject):
    """Typed governance subject for defect cluster report synthesis."""

    subject_kind: ClassVar[str] = "defect_cluster"

    cluster_id: str
    category: str
    tenant_id: str
    incident_count: int
    evidence_quality: str
    metadata: Mapping[str, Any] = field(default_factory=_empty_json_object)
    kind: SubjectKind = SubjectKind.CLUSTER

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "cluster_id": self.cluster_id,
            "category": self.category,
            "tenant_id": self.tenant_id,
            "incident_count": self.incident_count,
            "evidence_quality": self.evidence_quality,
            "metadata": dict(self.metadata),
        }


__all__ = ["ClusterGovernanceSubject"]
