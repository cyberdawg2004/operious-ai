"""Coordination execution traces.

Two trace shapes — same discipline as `GovernanceTrace` /
`SupervisorTrace`:

* `CoordinationTraceContext` — the input-side identity bundle every
                                dispatch carries. It is the
                                propagation handle through which
                                callers thread `(coordination_id,
                                correlation_id, request_id,
                                tenant_id, parent ids)` from one
                                operational stage to the next. The
                                context never raises; it never
                                changes; it is opaque to anything
                                outside the substrate.
* `CoordinationTrace`        — one per `CoordinationRuntime.dispatch()`
                                call. Carries everything an auditor /
                                replay tool needs to reconstruct the
                                dispatch lineage (sender, recipient,
                                governance decision id, status,
                                latency, parent identifiers).

Both are frozen, slotted, JSON-coercible via the persistence-layer
record converters. The trace is the **single** lineage artifact the
substrate emits per dispatch; the persisted `CoordinationRecord`
embeds a subset of the trace fields plus the message body.
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
    CoordinationStatus,
)
from app.coordination.identity import (
    CoordinationCorrelationId,
    CoordinationId,
    CoordinationMessageId,
)


@dataclass(frozen=True, slots=True)
class CoordinationTraceContext:
    """Lineage identifiers propagated through one coordination chain.

    Attributes:
        coordination_id:        Stable id for THIS dispatch. The
                                runtime mints one if the caller does
                                not provide an override.
        correlation_id:         Optional pipeline-level grouping. The
                                same `correlation_id` appears on every
                                dispatch belonging to one logical
                                operation. Threads into the
                                `GovernanceContext.correlation_id` of
                                each governance evaluation the
                                substrate triggers.
        parent_coordination_id: Optional id of the dispatch that
                                CAUSED this one (the causality
                                ancestor at the dispatch level).
        parent_message_id:      Optional id of the message that
                                CAUSED this one (the causality
                                ancestor at the message level — e.g.
                                the REQUEST a RESPONSE replies to).
        request_id:             Platform-wide request id (sourced via
                                `app.observability.context` when not
                                explicitly supplied).
        tenant_id:              Tenant scope.

    The context is hashable and immutable — it is safe to embed as a
    dict key, to pass across `await` boundaries, and to compare for
    equality in replay tests.
    """

    coordination_id: CoordinationId
    correlation_id: CoordinationCorrelationId | None = None
    parent_coordination_id: CoordinationId | None = None
    parent_message_id: CoordinationMessageId | None = None
    request_id: str | None = None
    tenant_id: str | None = None


@dataclass(frozen=True, slots=True)
class CoordinationTrace:
    """Apex trace for one `CoordinationRuntime.dispatch()` invocation.

    Carries the full lineage the substrate emits per dispatch. The
    persisted `CoordinationRecord` embeds a subset of these fields
    plus the payload body. Two fields deserve specific notice:

    * ``sequence`` — monotonic per-runtime-instance ordering field
      assigned by the runtime under a lock. Replay tools sort by
      ``(runtime_instance_id, sequence)`` for deterministic order
      reconstruction.
    * ``governance_decision_id`` — the apex `GovernanceDecision.decision_id`
      the substrate received from the `GovernanceRuntime`. Pairs the
      coordination trace with the governance trace at audit time.
    """

    coordination_id: CoordinationId
    message_id: CoordinationMessageId
    runtime_instance_id: uuid.UUID
    sequence: int
    sender_id: str
    recipient_id: str
    recipient_kind: str
    message_type: CoordinationMessageType
    direction: CoordinationDirection
    priority: CoordinationPriority
    status: CoordinationStatus
    correlation_id: CoordinationCorrelationId | None
    parent_coordination_id: CoordinationId | None
    parent_message_id: CoordinationMessageId | None
    in_reply_to: CoordinationMessageId | None
    request_id: str | None
    tenant_id: str | None
    governance_decision_id: uuid.UUID | None
    governance_chain_id: str | None
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    error: str | None = None
    tenant_authority_source: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["CoordinationTraceContext", "CoordinationTrace"]
