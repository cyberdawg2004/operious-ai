"""`EscalationPathEvaluator` — declared escalation chain witness.

For escalation-shaped dispatches the evaluator confirms an
escalation path is declared between sender and recipient. When the
dispatch is NOT escalation-shaped the evaluator stays silent.

A dispatch is escalation-shaped when EITHER:

* the dispatch `direction` is `AGENT_TO_SUPERVISOR`, OR
* there is a declared `ESCALATION`-kind edge between the sender
  and recipient nodes.

Verdict mapping:

* If escalation-shaped AND a declared escalation path covers the
  pair → ESCALATED finding (with the matching path id annotated).
* If escalation-shaped AND no declared escalation path covers the
  pair → DENIED finding (`ESCALATION_PATH_MISSING`).
* Otherwise → no findings.

The evaluator never emits ALLOWED; non-escalation dispatches are
left to `AllowedPathEvaluator`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar

from app.coordination.enums import CoordinationDirection
from app.coordination.topology.contracts.requests import (
    CoordinationTopologyEvaluationRequest,
)
from app.coordination.topology.enums import (
    CoordinationTopologyDecision,
    TopologyEdgeKind,
)
from app.coordination.topology.evaluators.base import (
    BaseCoordinationTopologyEvaluator,
)
from app.coordination.topology.identity import derive_finding_id
from app.coordination.topology.models.findings import (
    CoordinationTopologyFinding,
)
from app.coordination.topology.models.topology import (
    CoordinationTopology,
)
from app.coordination.topology.taxonomy import (
    CoordinationTopologyFindingCode,
)


class EscalationPathEvaluator(BaseCoordinationTopologyEvaluator):
    """Escalation-chain witness evaluator."""

    name: ClassVar[str] = "escalation_path"

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

        # Detect escalation shape.
        is_escalation_direction = (
            request.direction is CoordinationDirection.AGENT_TO_SUPERVISOR
        )
        candidate_edges = topology.edges_between(
            source_node_id=sender_node.node_id,
            target_node_id=recipient_node.node_id,
        )
        has_escalation_edge = any(
            edge.kind is TopologyEdgeKind.ESCALATION
            for edge in candidate_edges
        )
        if not (is_escalation_direction or has_escalation_edge):
            return ()

        # Match against declared escalation paths.
        for path in topology.escalation_paths:
            if (
                path.source_node_id == sender_node.node_id
                and path.target_node_id == recipient_node.node_id
            ):
                return (
                    self._finding(
                        request=request,
                        decision=CoordinationTopologyDecision.ESCALATED,
                        code=CoordinationTopologyFindingCode.ESCALATION_PATH_AUTHORIZED,
                        message=(
                            f"escalation path {path.path_id!r} authorises "
                            f"{request.sender_id!r} → "
                            f"{request.recipient_id!r}"
                        ),
                        ordinal=0,
                        source_node_id=sender_node.node_id,
                        target_node_id=recipient_node.node_id,
                        path_id=path.path_id,
                    ),
                )

        return (
            self._finding(
                request=request,
                decision=CoordinationTopologyDecision.DENIED,
                code=CoordinationTopologyFindingCode.ESCALATION_PATH_MISSING,
                message=(
                    f"escalation dispatch has no declared escalation "
                    f"path {request.sender_id!r} → "
                    f"{request.recipient_id!r}"
                ),
                ordinal=0,
                source_node_id=sender_node.node_id,
                target_node_id=recipient_node.node_id,
            ),
        )

    # ─── Internals ───────────────────────────────────────────────────

    def _finding(
        self,
        *,
        request: CoordinationTopologyEvaluationRequest,
        decision: CoordinationTopologyDecision,
        code: CoordinationTopologyFindingCode,
        message: str,
        ordinal: int,
        source_node_id=None,  # type: ignore[no-untyped-def]
        target_node_id=None,  # type: ignore[no-untyped-def]
        path_id: str | None = None,
    ) -> CoordinationTopologyFinding:
        seed_uuid = (
            request.evaluation_id_override
            if request.evaluation_id_override is not None
            else request.coordination_id
        )
        finding_id = derive_finding_id(
            evaluation_id=seed_uuid,
            evaluator_name=EscalationPathEvaluator.name,
            code=str(code),
            ordinal=ordinal,
        )
        return CoordinationTopologyFinding(
            finding_id=finding_id,
            evaluator_name=EscalationPathEvaluator.name,
            decision=decision,
            code=str(code),
            message=message,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            path_id=path_id,
            detected_at=datetime.now(timezone.utc),
        )


__all__ = ["EscalationPathEvaluator"]
