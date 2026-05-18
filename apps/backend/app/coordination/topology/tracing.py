"""Coordination topology traces.

Two trace shapes — same discipline as the parent coordination
substrate and sibling policy substrate:

* `CoordinationTopologyTraceContext`  — identity bundle propagated
                                         into / out of an evaluation.
* `CoordinationTopologyTrace`         — one per
                                         `CoordinationTopologyRuntime.evaluate()`
                                         call. Pairs 1:1 with the
                                         `CoordinationTopologyEvaluationResult`.

Both are frozen, slotted, replay-safe. The trace is the lineage
artefact the persistence layer embeds into
`CoordinationTopologyRecord`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
    CoordinationPriority,
)
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


@dataclass(frozen=True, slots=True)
class CoordinationTopologyTraceContext:
    """Lineage identifiers propagated through a topology evaluation."""

    evaluation_id: CoordinationTopologyEvaluationId
    chain_id: CoordinationTopologyChainId
    topology_id: CoordinationTopologyId
    coordination_id: CoordinationId
    coordination_message_id: CoordinationMessageId
    correlation_id: CoordinationCorrelationId | None = None
    parent_coordination_id: CoordinationId | None = None
    parent_message_id: CoordinationMessageId | None = None
    request_id: str | None = None
    tenant_id: str | None = None


@dataclass(frozen=True, slots=True)
class CoordinationTopologyTrace:
    """Apex trace for one `CoordinationTopologyRuntime.evaluate()` call."""

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
    direction: CoordinationDirection
    message_type: CoordinationMessageType
    priority: CoordinationPriority
    aggregate_decision: CoordinationTopologyDecision
    evaluator_names: tuple[str, ...]
    finding_count: int
    chain_depth: int
    max_chain_depth: int
    matched_edge_id: TopologyEdgeId | None
    matched_path_id: str | None
    correlation_id: CoordinationCorrelationId | None
    parent_coordination_id: CoordinationId | None
    parent_message_id: CoordinationMessageId | None
    request_id: str | None
    tenant_id: str | None
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    tenant_authority_source: str | None = None


__all__ = [
    "CoordinationTopologyTraceContext",
    "CoordinationTopologyTrace",
]
