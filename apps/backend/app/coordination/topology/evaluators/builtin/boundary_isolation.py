"""`BoundaryIsolationEvaluator` — authority-boundary policing.

Cross-boundary dispatches must honour each boundary's crossing
mode (`FORBIDDEN`, `DECLARED_EDGES`, `ALLOWLIST`). The evaluator
emits one finding per boundary the dispatch interacts with:

* same-boundary or boundary-unknown nodes → no finding,
* cross-boundary authorised (via the boundary's crossing rule) →
  `ALLOWED` finding with `BOUNDARY_CROSSING_AUTHORIZED` code,
* cross-boundary unauthorised → `BOUNDARY_VIOLATION` finding.

The runtime aggregator picks the most specific verdict; multiple
ALLOWED findings (one per crossed boundary) are fine and do not
weaken the apex decision.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar

from app.coordination.topology.contracts.requests import (
    CoordinationTopologyEvaluationRequest,
)
from app.coordination.topology.enums import (
    CoordinationTopologyDecision,
)
from app.coordination.topology.evaluators.base import (
    BaseCoordinationTopologyEvaluator,
)
from app.coordination.topology.identity import (
    TopologyNodeId,
    derive_finding_id,
)
from app.coordination.topology.models.findings import (
    CoordinationTopologyFinding,
)
from app.coordination.topology.models.topology import (
    CoordinationTopology,
)
from app.coordination.topology.taxonomy import (
    CoordinationTopologyFindingCode,
)


class BoundaryIsolationEvaluator(BaseCoordinationTopologyEvaluator):
    """Authority-boundary policing evaluator."""

    name: ClassVar[str] = "boundary_isolation"

    def __init__(self, topology: CoordinationTopology) -> None:
        self._topology = topology

    @property
    def topology(self) -> CoordinationTopology:
        return self._topology

    async def evaluate(
        self, request: CoordinationTopologyEvaluationRequest
    ) -> tuple[CoordinationTopologyFinding, ...]:
        topology = self._topology
        sender_node = topology.node_by_participant(request.sender_id)
        recipient_node = topology.node_by_participant(request.recipient_id)
        if sender_node is None or recipient_node is None:
            return ()

        findings: list[CoordinationTopologyFinding] = []
        ordinal = 0

        # Pre-compute whether the dispatch traverses a declared edge
        # that *explicitly* annotates a boundary as crossed. Used by
        # `DECLARED_EDGES` crossing mode.
        candidate_edges = topology.edges_between(
            source_node_id=sender_node.node_id,
            target_node_id=recipient_node.node_id,
        )

        for boundary in topology.boundaries:
            sender_inside = boundary.contains(sender_node.node_id)
            recipient_inside = boundary.contains(recipient_node.node_id)

            if sender_inside == recipient_inside:
                # Both inside or both outside — not a crossing.
                continue

            traversed_via_declared_edge = any(
                edge.crosses_boundary_id == boundary.boundary_id
                for edge in candidate_edges
            )
            if boundary.allows_crossing(
                source_node_id=sender_node.node_id,
                target_node_id=recipient_node.node_id,
                traversed_via_declared_edge=traversed_via_declared_edge,
            ):
                findings.append(
                    self._finding(
                        request=request,
                        decision=CoordinationTopologyDecision.ALLOWED,
                        code=CoordinationTopologyFindingCode.BOUNDARY_CROSSING_AUTHORIZED,
                        message=(
                            f"boundary {boundary.boundary_id!r} authorises "
                            f"crossing {request.sender_id!r} → "
                            f"{request.recipient_id!r}"
                        ),
                        ordinal=ordinal,
                        boundary_id=boundary.boundary_id,
                        source_node_id=sender_node.node_id,
                        target_node_id=recipient_node.node_id,
                    )
                )
            else:
                findings.append(
                    self._finding(
                        request=request,
                        decision=CoordinationTopologyDecision.BOUNDARY_VIOLATION,
                        code=CoordinationTopologyFindingCode.BOUNDARY_CROSSING_FORBIDDEN,
                        message=(
                            f"boundary {boundary.boundary_id!r} forbids "
                            f"crossing {request.sender_id!r} → "
                            f"{request.recipient_id!r}"
                        ),
                        ordinal=ordinal,
                        boundary_id=boundary.boundary_id,
                        source_node_id=sender_node.node_id,
                        target_node_id=recipient_node.node_id,
                    )
                )
            ordinal += 1

        return tuple(findings)

    # ─── Internals ───────────────────────────────────────────────────

    def _finding(
        self,
        *,
        request: CoordinationTopologyEvaluationRequest,
        decision: CoordinationTopologyDecision,
        code: CoordinationTopologyFindingCode,
        message: str,
        ordinal: int,
        boundary_id: str,
        source_node_id: TopologyNodeId,
        target_node_id: TopologyNodeId,
    ) -> CoordinationTopologyFinding:
        seed_uuid = (
            request.evaluation_id_override
            if request.evaluation_id_override is not None
            else request.coordination_id
        )
        finding_id = derive_finding_id(
            evaluation_id=seed_uuid,
            evaluator_name=BoundaryIsolationEvaluator.name,
            code=str(code),
            ordinal=ordinal,
        )
        return CoordinationTopologyFinding(
            finding_id=finding_id,
            evaluator_name=BoundaryIsolationEvaluator.name,
            decision=decision,
            code=str(code),
            message=message,
            boundary_id=boundary_id,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            detected_at=datetime.now(timezone.utc),
        )


__all__ = ["BoundaryIsolationEvaluator"]
