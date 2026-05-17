"""`AuthorityBoundary` — a declared structural boundary.

Boundaries are the topology layer's mechanism for expressing strict
isolation between groups of nodes (tenant boundaries, governance-
domain boundaries, operational-domain boundaries, environment
boundaries).

Each boundary declares:

* `kind`            — its classification.
* `boundary_id`     — stable id (string for readability).
* `member_node_ids` — the set of nodes inside the boundary.
* `crossing`        — how the boundary may be crossed
                       (`FORBIDDEN`, `DECLARED_EDGES`, `ALLOWLIST`).
* `allowed_crossing_pairs`
                     — when `crossing == ALLOWLIST`, the explicit
                       ordered pairs of `(source, target)` node ids
                       that may cross the boundary.

The `BoundaryIsolationEvaluator` consults boundaries on every
dispatch and emits `BOUNDARY_VIOLATION` when an unauthorised
crossing is attempted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.coordination.topology.enums import (
    TopologyBoundaryCrossing,
    TopologyBoundaryKind,
)
from app.coordination.topology.identity import TopologyNodeId


@dataclass(frozen=True, slots=True)
class AuthorityBoundary:
    """One declared authority boundary.

    Attributes:
        boundary_id:             Stable identifier.
        kind:                    Classification.
        display_name:            Short human-readable name.
        member_node_ids:         Frozen tuple of node ids inside
                                  this boundary.
        crossing:                Crossing-mode classification.
        allowed_crossing_pairs:  Directional allowlist for
                                  cross-boundary dispatches when
                                  `crossing == ALLOWLIST`.
        metadata:                Free-form, propagated through
                                  persistence.
    """

    boundary_id: str
    kind: TopologyBoundaryKind
    display_name: str = ""
    member_node_ids: tuple[TopologyNodeId, ...] = ()
    crossing: TopologyBoundaryCrossing = (
        TopologyBoundaryCrossing.FORBIDDEN
    )
    allowed_crossing_pairs: tuple[
        tuple[TopologyNodeId, TopologyNodeId], ...
    ] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def contains(self, node_id: TopologyNodeId) -> bool:
        return node_id in self.member_node_ids

    def allows_crossing(
        self,
        *,
        source_node_id: TopologyNodeId,
        target_node_id: TopologyNodeId,
        traversed_via_declared_edge: bool,
    ) -> bool:
        """Decide whether the (source → target) dispatch may cross.

        Caller is responsible for ensuring `source` and `target` lie
        on opposite sides of the boundary; the method does NOT
        re-check membership.

        * `FORBIDDEN`       → always False.
        * `DECLARED_EDGES`  → True iff the dispatch traverses an
                              edge that explicitly annotates this
                              boundary as crossed
                              (`traversed_via_declared_edge`).
        * `ALLOWLIST`       → True iff `(source, target)` is in
                              `allowed_crossing_pairs`.
        """
        match self.crossing:
            case TopologyBoundaryCrossing.FORBIDDEN:
                return False
            case TopologyBoundaryCrossing.DECLARED_EDGES:
                return traversed_via_declared_edge
            case TopologyBoundaryCrossing.ALLOWLIST:
                return (
                    source_node_id,
                    target_node_id,
                ) in self.allowed_crossing_pairs

    def to_dict(self) -> dict[str, Any]:
        return {
            "boundary_id": self.boundary_id,
            "kind": self.kind.value,
            "display_name": self.display_name,
            "member_node_ids": [str(n) for n in self.member_node_ids],
            "crossing": self.crossing.value,
            "allowed_crossing_pairs": [
                [str(s), str(t)]
                for (s, t) in self.allowed_crossing_pairs
            ],
            "metadata": dict(self.metadata),
        }


__all__ = ["AuthorityBoundary"]
