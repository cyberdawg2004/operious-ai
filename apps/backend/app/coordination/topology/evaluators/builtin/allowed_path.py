"""`AllowedPathEvaluator` — sender→recipient edge authorisation.

Resolves the dispatch's (sender, recipient) pair against the
declared topology nodes, then looks up declared edges between the
two nodes. The evaluator emits ONE finding:

* `ALLOWED`  — the topology has at least one declared edge from
                source to target whose direction + message type
                accept the dispatch.
* `DENIED`   — the topology declares no matching edge, either
                because the sender / recipient is unknown, no edge
                between them exists, or the edge constraints don't
                match the dispatch.

Determinism: candidate edges are walked in declaration order; the
first matching edge is captured on the ALLOWED finding's
`edge_id` (so the audit trail records *which* declared edge
authorised the dispatch).
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


class AllowedPathEvaluator(BaseCoordinationTopologyEvaluator):
    """Authorise (sender, recipient) against declared edges."""

    name: ClassVar[str] = "allowed_path"

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

        if sender_node is None:
            return (
                self._finding(
                    request=request,
                    decision=CoordinationTopologyDecision.DENIED,
                    code=CoordinationTopologyFindingCode.PATH_UNKNOWN_SENDER,
                    message=(
                        f"sender {request.sender_id!r} is not a "
                        f"declared topology node"
                    ),
                    ordinal=0,
                ),
            )
        if recipient_node is None:
            return (
                self._finding(
                    request=request,
                    decision=CoordinationTopologyDecision.DENIED,
                    code=CoordinationTopologyFindingCode.PATH_UNKNOWN_RECIPIENT,
                    message=(
                        f"recipient {request.recipient_id!r} is not a "
                        f"declared topology node"
                    ),
                    ordinal=0,
                    source_node_id=sender_node.node_id,
                ),
            )

        candidate_edges = topology.edges_between(
            source_node_id=sender_node.node_id,
            target_node_id=recipient_node.node_id,
        )
        if not candidate_edges:
            return (
                self._finding(
                    request=request,
                    decision=CoordinationTopologyDecision.DENIED,
                    code=CoordinationTopologyFindingCode.PATH_DENIED,
                    message=(
                        f"no declared edge "
                        f"{request.sender_id!r} → {request.recipient_id!r}"
                    ),
                    ordinal=0,
                    source_node_id=sender_node.node_id,
                    target_node_id=recipient_node.node_id,
                ),
            )

        # Sort candidate edges by (priority, declaration index) so the
        # winning edge is deterministic across replays.
        ordered = sorted(
            enumerate(candidate_edges),
            key=lambda pair: (pair[1].priority, pair[0]),
        )

        # Walk in priority order; return ALLOWED on first compatible
        # edge. If none are compatible, emit a single DENIED finding
        # that records the most specific failure reason.
        for _, edge in ordered:
            if not edge.matches_direction(request.direction):
                continue
            if not edge.matches_message_type(request.message_type):
                continue
            return (
                self._finding(
                    request=request,
                    decision=CoordinationTopologyDecision.ALLOWED,
                    code=CoordinationTopologyFindingCode.PATH_ALLOWED,
                    message=(
                        f"edge authorises {request.sender_id!r} → "
                        f"{request.recipient_id!r}"
                    ),
                    ordinal=0,
                    source_node_id=sender_node.node_id,
                    target_node_id=recipient_node.node_id,
                    edge_id_value=edge.edge_id,
                ),
            )

        # Edges exist but none match direction / message_type. Build
        # a single DENIED finding with the most specific code.
        for _, edge in ordered:
            if not edge.matches_direction(request.direction):
                return (
                    self._finding(
                        request=request,
                        decision=CoordinationTopologyDecision.DENIED,
                        code=CoordinationTopologyFindingCode.PATH_FORBIDDEN_DIRECTION,
                        message=(
                            f"no edge authorises direction "
                            f"{request.direction.value!r}"
                        ),
                        ordinal=0,
                        source_node_id=sender_node.node_id,
                        target_node_id=recipient_node.node_id,
                    ),
                )
        return (
            self._finding(
                request=request,
                decision=CoordinationTopologyDecision.DENIED,
                code=CoordinationTopologyFindingCode.PATH_FORBIDDEN_MESSAGE_TYPE,
                message=(
                    f"no edge authorises message type "
                    f"{request.message_type.value!r}"
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
        edge_id_value=None,  # type: ignore[no-untyped-def]
    ) -> CoordinationTopologyFinding:
        seed_uuid = (
            request.evaluation_id_override
            if request.evaluation_id_override is not None
            else request.coordination_id
        )
        finding_id = derive_finding_id(
            evaluation_id=seed_uuid,
            evaluator_name=AllowedPathEvaluator.name,
            code=str(code),
            ordinal=ordinal,
        )
        return CoordinationTopologyFinding(
            finding_id=finding_id,
            evaluator_name=AllowedPathEvaluator.name,
            decision=decision,
            code=str(code),
            message=message,
            edge_id=edge_id_value,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            detected_at=datetime.now(timezone.utc),
        )


__all__ = ["AllowedPathEvaluator"]
