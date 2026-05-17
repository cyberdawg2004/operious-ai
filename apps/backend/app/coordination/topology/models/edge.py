"""`CoordinationEdge` — a declared directed edge between two nodes.

An edge is the atomic unit of topology authorisation: "node A may
send `<message_types>` to node B in `<direction>`, traversing
`<edge_kind>` semantics".

Edges are immutable and order-significant only via `priority`
(stable secondary sort key after natural insertion order). Two
edges with identical `(source_node_id, target_node_id, direction)`
are permitted — they may declare distinct allowed message types or
distinct edge kinds.

Edges do NOT carry executable code — they describe structural
authorisation. The `AllowedPathEvaluator` interprets them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
)
from app.coordination.topology.enums import TopologyEdgeKind
from app.coordination.topology.identity import (
    TopologyEdgeId,
    TopologyNodeId,
)


@dataclass(frozen=True, slots=True)
class CoordinationEdge:
    """One declared directed edge between two topology nodes.

    Attributes:
        edge_id:            Stable identifier.
        source_node_id:     Origin node.
        target_node_id:     Destination node.
        kind:               Edge classification.
        direction:          Allowed coordination direction for this
                             edge. ``None`` matches any direction.
        allowed_message_types:
                             Tuple of message types this edge
                             authorises. Empty tuple = any message
                             type allowed.
        crosses_boundary_id:
                             When set, declares that this edge
                             explicitly traverses the named authority
                             boundary. Required for boundary crossings
                             under `DECLARED_EDGES` crossing mode.
        description:        Short human-readable description.
        priority:            Stable secondary ordering key used by
                             the `AllowedPathEvaluator` when several
                             edges match. Lower number = higher
                             priority. Two equal-priority matches
                             are resolved by declared insertion
                             order.
        metadata:            Free-form, propagated through persistence.
    """

    edge_id: TopologyEdgeId
    source_node_id: TopologyNodeId
    target_node_id: TopologyNodeId
    kind: TopologyEdgeKind
    direction: CoordinationDirection | None = None
    allowed_message_types: tuple[CoordinationMessageType, ...] = ()
    crosses_boundary_id: str | None = None
    description: str = ""
    priority: int = 100
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def matches_message_type(
        self, message_type: CoordinationMessageType
    ) -> bool:
        """True iff `message_type` is permitted by this edge.

        Empty `allowed_message_types` is interpreted as "any message
        type allowed" — a deliberate convenience for declaring
        broadly-permissive edges.
        """
        return (
            not self.allowed_message_types
            or message_type in self.allowed_message_types
        )

    def matches_direction(
        self, direction: CoordinationDirection
    ) -> bool:
        """True iff `direction` is permitted by this edge.

        `None` on the edge is interpreted as "any direction allowed".
        """
        return self.direction is None or self.direction == direction

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": str(self.edge_id),
            "source_node_id": str(self.source_node_id),
            "target_node_id": str(self.target_node_id),
            "kind": self.kind.value,
            "direction": (
                self.direction.value if self.direction is not None else None
            ),
            "allowed_message_types": [
                m.value for m in self.allowed_message_types
            ],
            "crosses_boundary_id": self.crosses_boundary_id,
            "description": self.description,
            "priority": self.priority,
            "metadata": dict(self.metadata),
        }


__all__ = ["CoordinationEdge"]
