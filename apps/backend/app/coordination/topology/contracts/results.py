"""`CoordinationTopologyEvaluationResult` — apex output of `evaluate()`.

Pairs 1:1 with `CoordinationTopologyTrace`. The persistence layer's
serialisers convert `(result, trace)` into the
`CoordinationTopologyRecord`.

Determinism contract:

* `findings` preserves evaluator-sort order, then per-evaluator
  emission order.
* `aggregate_decision` is computed via
  `coordination_topology_precedence` (most-restrictive wins) over
  every finding's decision; `ALLOWED` is the baseline when no
  findings are emitted.
* `matched_edge_id` / `matched_path_id` surface the structural
  witness that drove the apex decision when it was non-trivially
  derived (the topology authorised a specific edge / path / boundary
  decision).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.coordination.identity import (
    CoordinationCorrelationId,
    CoordinationId,
    CoordinationMessageId,
)
from app.coordination.topology.enums import (
    CoordinationTopologyDecision,
)
from app.coordination.topology.identity import (
    CoordinationTopologyChainId,
    CoordinationTopologyEvaluationId,
    CoordinationTopologyId,
    TopologyEdgeId,
)
from app.coordination.topology.models.findings import (
    CoordinationTopologyFinding,
)


@dataclass(frozen=True, slots=True)
class CoordinationTopologyEvaluationResult:
    """Apex result of one coordination-topology evaluation.

    Attributes:
        evaluation_id:        Stable identifier of THIS evaluation.
        chain_id:             Stable identifier of the evaluator-chain
                               composition that ran.
        topology_id:          Identifier of the declared topology
                               the evaluators consulted.
        topology_name:        Human-readable name of the topology.
        topology_version:     Version handle.
        runtime_instance_id:  Stable id of the
                               `CoordinationTopologyRuntime` instance.
        sequence:             Monotonic per-runtime-instance ordering.
        coordination_id /
        coordination_message_id:
                               Coordination lineage handles.
        sender_id / recipient_id /
        recipient_kind:       Routing identity captured verbatim.
        aggregate_decision:   Apex verdict; precedence-aggregated.
        findings:             All findings, in evaluator-sort then
                               emission order.
        matched_edge_id:      Edge that drove the apex decision
                               (when applicable).
        matched_path_id:      Path that drove the apex decision
                               (when applicable).
        evaluator_names:      Names of evaluators that contributed.
        chain_depth:          Reported chain depth (verbatim from
                               request).
        max_chain_depth:      Topology's `max_chain_depth` (recorded
                               for audit).
        reason:               Short human-readable explanation.
        started_at / ended_at:Wall-clock window.
        latency_ms:           Total evaluation latency.
        correlation_id / parent_*:
                               Lineage handles.
        request_id / tenant_id:
                               Platform + tenant lineage.
        error:                Set when the framework itself failed.
        metadata:             Free-form, propagated from request.
    """

    evaluation_id: CoordinationTopologyEvaluationId
    chain_id: CoordinationTopologyChainId
    topology_id: CoordinationTopologyId
    topology_name: str
    topology_version: str
    runtime_instance_id: uuid.UUID
    sequence: int
    coordination_id: CoordinationId
    coordination_message_id: CoordinationMessageId
    sender_id: str
    recipient_id: str
    recipient_kind: str
    aggregate_decision: CoordinationTopologyDecision
    findings: tuple[CoordinationTopologyFinding, ...]
    evaluator_names: tuple[str, ...]
    chain_depth: int
    max_chain_depth: int
    reason: str
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    matched_edge_id: TopologyEdgeId | None = None
    matched_path_id: str | None = None
    correlation_id: CoordinationCorrelationId | None = None
    parent_coordination_id: CoordinationId | None = None
    parent_message_id: CoordinationMessageId | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_allowed(self) -> bool:
        return (
            self.aggregate_decision
            is CoordinationTopologyDecision.ALLOWED
        )

    @property
    def is_blocking(self) -> bool:
        """True iff the apex verdict halts dispatch.

        Delegates to `is_blocking_topology_decision` — the single
        authority on blocking semantics across the substrate.
        """
        from app.coordination.topology.taxonomy import (
            is_blocking_topology_decision,
        )

        return is_blocking_topology_decision(self.aggregate_decision)


__all__ = ["CoordinationTopologyEvaluationResult"]
