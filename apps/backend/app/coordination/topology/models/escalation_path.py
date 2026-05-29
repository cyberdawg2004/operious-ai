"""`EscalationPath` — a declared escalation chain.

Escalation paths are structurally identical to `CoordinationPath`s
but carry escalation-specific semantics:

* every edge in the chain MUST be a declared
  `TopologyEdgeKind.ESCALATION` edge,
* the path's `seniority_ordering` field captures the authority
  chain (the path proceeds from least-senior to most-senior).

The `EscalationPathEvaluator` matches dispatches whose source /
target endpoints align with a declared escalation path and emits
an `ESCALATED` finding for replay-safe audit lineage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.coordination.topology.identity import TopologyNodeId


@dataclass(frozen=True, slots=True)
class EscalationPath:
    """One declared escalation chain.

    Attributes:
        path_id:             Stable, deployment-pinned identifier.
        node_ids:             Ordered tuple of node ids. Length >= 2.
        seniority_ordering:   Tuple of seniority annotations
                               (free-form strings) for each node, in
                               the same order as `node_ids`. The
                               substrate does not interpret the
                               strings; they surface in audit /
                               supervisor consumption.
        description:         Short human-readable description.
        metadata:            Free-form, propagated through persistence.
    """

    path_id: str
    node_ids: tuple[TopologyNodeId, ...]
    seniority_ordering: tuple[str, ...] = ()
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    @property
    def source_node_id(self) -> TopologyNodeId:
        return self.node_ids[0]

    @property
    def target_node_id(self) -> TopologyNodeId:
        return self.node_ids[-1]

    @property
    def depth(self) -> int:
        """Hop count along the escalation chain."""
        return len(self.node_ids) - 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "path_id": self.path_id,
            "node_ids": [str(n) for n in self.node_ids],
            "seniority_ordering": list(self.seniority_ordering),
            "description": self.description,
            "metadata": dict(self.metadata),
        }


__all__ = ["EscalationPath"]
