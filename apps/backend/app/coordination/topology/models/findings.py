"""`CoordinationTopologyFinding` — one structural observation.

A finding is the atomic unit of topology output. An evaluator emits
zero or more findings per request; the runtime aggregates findings
across the evaluator chain into one apex
`CoordinationTopologyEvaluationResult`.

Findings link back to:

* the originating evaluator (`evaluator_name`),
* the structural witness that triggered them (`edge_id`,
  `path_id`, `boundary_id`, `node_id`) where applicable.

The rich shape lets supervisor / audit consumers reconstruct the
full structural-decision lineage from persisted findings without
re-running evaluators.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.coordination.topology.enums import (
    CoordinationTopologyDecision,
)
from app.coordination.topology.identity import (
    TopologyEdgeId,
    TopologyNodeId,
)


@dataclass(frozen=True, slots=True)
class CoordinationTopologyFinding:
    """One structural-authorisation finding.

    Attributes:
        finding_id:     Stable UUID. Derived via `derive_finding_id`
                         for replay-safety.
        evaluator_name: Stable name of the emitting evaluator.
        decision:       Verdict carried by this finding.
        code:           Stable code (typically from
                         `CoordinationTopologyFindingCode`).
        message:        Short human-readable description.
        edge_id:        Originating edge (when known).
        path_id:        Originating path id (when known).
        boundary_id:    Originating boundary id (when known).
        source_node_id: Sender node id (when known).
        target_node_id: Recipient node id (when known).
        detected_at:    Wall-clock timestamp (UTC).
        metadata:       Free-form, propagated through persistence.
    """

    finding_id: uuid.UUID
    evaluator_name: str
    decision: CoordinationTopologyDecision
    code: str
    message: str
    edge_id: TopologyEdgeId | None = None
    path_id: str | None = None
    boundary_id: str | None = None
    source_node_id: TopologyNodeId | None = None
    target_node_id: TopologyNodeId | None = None
    detected_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["CoordinationTopologyFinding"]
