"""`CoordinationPath` — an ordered sequence of declared nodes.

A path is the topology layer's declarative answer to "this multi-hop
sequence is structurally legal". Paths are not used to *plan*
dispatches; the coordination substrate is one-hop only by Sprint L1
Rule 4. Paths are used:

* as audit / supervisor surfaces ("which declared paths covered this
  dispatch?"),
* as a reachability witness for evaluators that prefer "matches a
  declared path" over "matches a declared edge",
* to surface the operational graph in inspection dashboards.

A path is internally consistent: every consecutive `(node_i,
node_i+1)` pair MUST correspond to a declared edge in the parent
topology. The topology constructor validates this invariant at
composition time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.coordination.topology.identity import TopologyNodeId


@dataclass(frozen=True, slots=True)
class CoordinationPath:
    """One declared multi-hop coordination path.

    Attributes:
        path_id:      Stable, deployment-pinned path identifier
                       (string for human-readability — matches the
                       `rule_id` convention from the policy
                       substrate).
        node_ids:     Ordered tuple of node ids the path traverses.
                       MUST contain at least two nodes (source +
                       target). The topology constructor enforces
                       this + the edge-consistency invariant.
        description:  Short human-readable description.
        metadata:     Free-form, propagated through persistence.
    """

    path_id: str
    node_ids: tuple[TopologyNodeId, ...]
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def source_node_id(self) -> TopologyNodeId:
        return self.node_ids[0]

    @property
    def target_node_id(self) -> TopologyNodeId:
        return self.node_ids[-1]

    @property
    def depth(self) -> int:
        """Hop count along the path. ``len(node_ids) - 1``."""
        return len(self.node_ids) - 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "path_id": self.path_id,
            "node_ids": [str(n) for n in self.node_ids],
            "description": self.description,
            "metadata": dict(self.metadata),
        }


__all__ = ["CoordinationPath"]
