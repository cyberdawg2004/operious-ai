"""`CoordinationTopology` — the apex declared structure.

A topology is an immutable, declarative description of the operational
graph the substrate is allowed to communicate over. Topologies are
NEVER mutated at runtime; new revisions become new
`CoordinationTopology` instances (future versioning support — see
`version` field).

The topology is internally consistent at construction time:

* every edge references known nodes,
* every path is a chain of declared edges,
* every escalation path is a chain of declared escalation edges,
* every boundary references known nodes.

Violations raise `CoordinationTopologyConfigurationError` at
composition time — fail-fast.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.coordination.topology.enums import TopologyEdgeKind
from app.coordination.topology.exceptions import (
    CoordinationTopologyConfigurationError,
)
from app.coordination.topology.identity import (
    CoordinationTopologyId,
    TopologyEdgeId,
    TopologyNodeId,
)
from app.coordination.topology.models.boundary import AuthorityBoundary
from app.coordination.topology.models.edge import CoordinationEdge
from app.coordination.topology.models.escalation_path import (
    EscalationPath,
)
from app.coordination.topology.models.node import CoordinationNode
from app.coordination.topology.models.path import CoordinationPath


_DEFAULT_MAX_CHAIN_DEPTH: int = 4


@dataclass(frozen=True, slots=True)
class CoordinationTopology:
    """An immutable, declarative operational graph.

    Attributes:
        topology_id:        Stable identifier.
        name:               Stable, human-readable name.
        version:            Free-form version handle for forward-
                             compatibility with versioned topology
                             declarations. Sprint L3 does NOT
                             implement versioning logic; the field
                             is here so future versions can land
                             without a structural break.
        nodes:              Declared nodes.
        edges:              Declared edges.
        paths:              Declared multi-hop coordination paths.
        escalation_paths:   Declared escalation chains.
        boundaries:         Declared authority boundaries.
        max_chain_depth:    Maximum chain depth the
                             `ChainDepthEvaluator` will permit.
                             Defaults to 4 (see
                             `_DEFAULT_MAX_CHAIN_DEPTH`).
        description:        Short human-readable description.
        metadata:           Free-form, propagated onto findings /
                             trace metadata.
    """

    topology_id: CoordinationTopologyId
    name: str
    nodes: tuple[CoordinationNode, ...]
    edges: tuple[CoordinationEdge, ...] = ()
    paths: tuple[CoordinationPath, ...] = ()
    escalation_paths: tuple[EscalationPath, ...] = ()
    boundaries: tuple[AuthorityBoundary, ...] = ()
    max_chain_depth: int = _DEFAULT_MAX_CHAIN_DEPTH
    version: str = "v1"
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def __post_init__(self) -> None:
        """Validate internal consistency at construction time."""
        if not self.nodes:
            raise CoordinationTopologyConfigurationError(
                "CoordinationTopology requires at least one node"
            )
        if self.max_chain_depth <= 0:
            raise CoordinationTopologyConfigurationError(
                "CoordinationTopology.max_chain_depth must be positive"
            )
        node_ids: set[TopologyNodeId] = {n.node_id for n in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise CoordinationTopologyConfigurationError(
                "duplicate node_id in CoordinationTopology.nodes"
            )
        participant_ids: set[str] = {n.participant_id for n in self.nodes}
        if len(participant_ids) != len(self.nodes):
            raise CoordinationTopologyConfigurationError(
                "duplicate participant_id in CoordinationTopology.nodes"
            )

        edge_pairs: set[tuple[TopologyNodeId, TopologyNodeId]] = set()
        edge_index: dict[
            tuple[TopologyNodeId, TopologyNodeId], list[CoordinationEdge]
        ] = {}
        for edge in self.edges:
            if edge.source_node_id not in node_ids:
                raise CoordinationTopologyConfigurationError(
                    f"edge {edge.edge_id!s} references unknown source"
                    f" node {edge.source_node_id!s}"
                )
            if edge.target_node_id not in node_ids:
                raise CoordinationTopologyConfigurationError(
                    f"edge {edge.edge_id!s} references unknown target"
                    f" node {edge.target_node_id!s}"
                )
            edge_pairs.add((edge.source_node_id, edge.target_node_id))
            edge_index.setdefault(
                (edge.source_node_id, edge.target_node_id), []
            ).append(edge)

        # Paths must traverse declared edges.
        for path in self.paths:
            if len(path.node_ids) < 2:
                raise CoordinationTopologyConfigurationError(
                    f"path {path.path_id!r} must contain at least two nodes"
                )
            for i in range(len(path.node_ids) - 1):
                pair = (path.node_ids[i], path.node_ids[i + 1])
                if pair not in edge_pairs:
                    raise CoordinationTopologyConfigurationError(
                        f"path {path.path_id!r} hop "
                        f"{path.node_ids[i]!s} → {path.node_ids[i + 1]!s} "
                        f"has no declared edge"
                    )

        # Escalation paths must traverse declared ESCALATION edges.
        for esc in self.escalation_paths:
            if len(esc.node_ids) < 2:
                raise CoordinationTopologyConfigurationError(
                    f"escalation path {esc.path_id!r} must contain at "
                    f"least two nodes"
                )
            for i in range(len(esc.node_ids) - 1):
                pair = (esc.node_ids[i], esc.node_ids[i + 1])
                matching = edge_index.get(pair, [])
                if not any(
                    edge.kind is TopologyEdgeKind.ESCALATION
                    for edge in matching
                ):
                    raise CoordinationTopologyConfigurationError(
                        f"escalation path {esc.path_id!r} hop "
                        f"{esc.node_ids[i]!s} → {esc.node_ids[i + 1]!s} "
                        f"has no declared ESCALATION edge"
                    )

        # Boundaries must reference known nodes.
        for boundary in self.boundaries:
            for member in boundary.member_node_ids:
                if member not in node_ids:
                    raise CoordinationTopologyConfigurationError(
                        f"boundary {boundary.boundary_id!r} references "
                        f"unknown node {member!s}"
                    )
            for source, target in boundary.allowed_crossing_pairs:
                if source not in node_ids or target not in node_ids:
                    raise CoordinationTopologyConfigurationError(
                        f"boundary {boundary.boundary_id!r} allowlist "
                        f"references unknown node"
                    )

    # ─── Inspection helpers ──────────────────────────────────────────

    def node_by_participant(
        self, participant_id: str
    ) -> CoordinationNode | None:
        """Return the declared node for `participant_id`, or None."""
        for node in self.nodes:
            if node.participant_id == participant_id:
                return node
        return None

    def edges_between(
        self,
        *,
        source_node_id: TopologyNodeId,
        target_node_id: TopologyNodeId,
    ) -> tuple[CoordinationEdge, ...]:
        """Return every declared edge from source → target, in declaration order."""
        return tuple(
            edge
            for edge in self.edges
            if edge.source_node_id == source_node_id
            and edge.target_node_id == target_node_id
        )

    def edge_by_id(
        self, edge_id: TopologyEdgeId
    ) -> CoordinationEdge | None:
        for edge in self.edges:
            if edge.edge_id == edge_id:
                return edge
        return None

    def boundaries_containing(
        self, node_id: TopologyNodeId
    ) -> tuple[AuthorityBoundary, ...]:
        return tuple(
            boundary
            for boundary in self.boundaries
            if boundary.contains(node_id)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "topology_id": str(self.topology_id),
            "name": self.name,
            "version": self.version,
            "max_chain_depth": self.max_chain_depth,
            "description": self.description,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "paths": [p.to_dict() for p in self.paths],
            "escalation_paths": [
                e.to_dict() for e in self.escalation_paths
            ],
            "boundaries": [b.to_dict() for b in self.boundaries],
            "metadata": dict(self.metadata),
        }


__all__ = ["CoordinationTopology"]
