"""Boundary traces.

Same discipline as every sibling substrate.

* `BoundaryTraceContext` — identity bundle propagated into / out
                            of an ingest/emit call.
* `BoundaryTrace`        — one per call. Pairs 1:1 with the
                            corresponding result.

The boundary trace deliberately preserves both the
**internal-substrate** lineage (correlation_id / request_id /
tenant_id) AND the **external-source** lineage
(source_type / source_id / external_message_id /
external_conversation_id) so audit consumers can reconstruct the
full path from external delivery to internal artifact.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.boundary.enums import (
    BoundaryDirection,
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.identity import (
    BoundaryEgressId,
    BoundaryEventId,
    BoundaryIngressId,
)


@dataclass(frozen=True, slots=True)
class BoundaryTraceContext:
    """Lineage identifiers propagated through a boundary call."""

    direction: BoundaryDirection
    source_type: BoundarySourceType
    source_id: str
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    external_message_id: str | None = None
    external_conversation_id: str | None = None


@dataclass(frozen=True, slots=True)
class BoundaryTrace:
    """Apex trace for one boundary call.

    The trace is direction-aware: `event_id` and replay fields
    are populated for INGRESS only; `egress_id` is populated for
    EGRESS only.
    """

    direction: BoundaryDirection
    runtime_instance_id: uuid.UUID
    sequence: int
    source_type: BoundarySourceType
    source_id: str
    adapter_name: str
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    external_message_id: str | None = None
    external_conversation_id: str | None = None
    # INGRESS-specific
    ingress_id: BoundaryIngressId | None = None
    event_id: BoundaryEventId | None = None
    normalization_status: BoundaryNormalizationStatus | None = None
    replay_disposition: BoundaryReplayDisposition | None = None
    # EGRESS-specific
    egress_id: BoundaryEgressId | None = None
    error: str | None = None
    # 2.5-G1: governance provenance — joinable id pair mirroring the
    # ``CoordinationEnvelope`` pattern. ``governance_decision_id`` is
    # the UUID of the apex ``GovernanceDecision`` whose verdict
    # caused this boundary call (typically the egress-time gate);
    # ``governance_chain_id`` is the human-readable chain handle the
    # decision came from. Both are ID-only — the boundary substrate
    # never imports governance internals; replay tools join by id
    # against the governance repository instead of re-evaluating.
    governance_decision_id: uuid.UUID | None = None
    governance_chain_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["BoundaryTraceContext", "BoundaryTrace"]
