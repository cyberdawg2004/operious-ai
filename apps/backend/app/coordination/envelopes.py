"""`CoordinationEnvelope` — immutable communication artifact.

Unlike the `GovernanceEnvelope` and `ExecutionInspectionEnvelope`
patterns (which are "never-raising containers around runtime
outputs"), the coordination envelope is the **persisted artifact
itself**: the durable, audit-grade, replay-safe record of one
coordination message dispatch.

Conceptual mapping:

* `CoordinationMessage`         — the message identity + content.
* `CoordinationEnvelope`        — message + dispatch lineage + status.
                                  THIS is what persists.
* `CoordinationDispatchResult`  — return value of `dispatch()`;
                                  wraps the envelope plus the
                                  substrate's outcome verdict.

Immutability discipline:

* `frozen=True, slots=True` — every field is set once at construction.
* Every nested value is itself frozen / immutable.
* Lists are tuples; mappings are `Mapping[str, Any]` (read-only by
  convention; the persistence layer enforces JSON serialisability).

Deterministic ordering:

* `sequence` is monotonic per runtime instance. Combined with
  `runtime_instance_id` it yields a globally-orderable key suitable
  for replay reconstruction.
* `created_at` (from the message) and `dispatched_at` (substrate-
  stamped) are recorded but are NOT the primary ordering key —
  wall-clock ordering is non-deterministic across replays.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.coordination.contracts.messages import CoordinationMessage
from app.coordination.enums import (
    CoordinationDirection,
    CoordinationStatus,
)
from app.coordination.identity import (
    CoordinationCorrelationId,
    CoordinationId,
    CoordinationMessageId,
)


@dataclass(frozen=True, slots=True)
class CoordinationEnvelope:
    """Immutable communication artifact for one coordination dispatch.

    Attributes:
        coordination_id:        Stable identifier of THIS dispatch.
        message:                The wrapped `CoordinationMessage`.
        direction:              Operational direction classification.
        status:                 Terminal lifecycle status. Always one
                                 of the terminal `CoordinationStatus`
                                 values; never PENDING when produced
                                 by `CoordinationRuntime.dispatch()`.
        sequence:               Monotonic per-runtime-instance order
                                 field assigned by the runtime under
                                 a lock. Combined with
                                 `runtime_instance_id` yields a
                                 globally-orderable key.
        runtime_instance_id:    Stable id of the
                                 `CoordinationRuntime` instance that
                                 produced the envelope. Process-
                                 lifetime scoped; replays carry the
                                 *original* value, not a fresh one.
        correlation_id:         Pipeline-level grouping.
        parent_coordination_id: Causality ancestor (dispatch).
        parent_message_id:      Causality ancestor (message).
        request_id:             Platform-wide request id.
        tenant_id:              Tenant scope.
        governance_decision_id: Apex `GovernanceDecision.decision_id`
                                 the substrate received. ``None`` for
                                 envelopes produced before governance
                                 ran (validation failures don't
                                 produce envelopes; this stays None
                                 only for tests / replay
                                 reconstruction outside the runtime).
        governance_chain_id:    Policy chain identifier that ran.
        created_at:             Caller-controlled message authoring
                                 timestamp (mirrored from the
                                 message).
        dispatched_at:          Substrate-stamped wall-clock time the
                                 dispatch completed.
        metadata:               Free-form, propagated through audit /
                                 replay.
    """

    coordination_id: CoordinationId
    message: CoordinationMessage
    direction: CoordinationDirection
    status: CoordinationStatus
    sequence: int
    runtime_instance_id: uuid.UUID
    correlation_id: CoordinationCorrelationId | None
    parent_coordination_id: CoordinationId | None
    parent_message_id: CoordinationMessageId | None
    request_id: str | None
    tenant_id: str | None
    governance_decision_id: uuid.UUID | None
    governance_chain_id: str | None
    created_at: datetime
    dispatched_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def message_id(self) -> CoordinationMessageId:
        """Convenience accessor — the wrapped message's id."""
        return self.message.message_id

    @property
    def is_delivered(self) -> bool:
        """True iff the envelope's status indicates the dispatch reached the recipient.

        DISPATCHED and DEGRADED count as "delivered" (the recipient
        is the substrate's authoritative destination; whether the
        recipient's runtime *acts* on the envelope is the
        orchestration layer's responsibility). DENIED, POLICY_DENIED,
        TOPOLOGY_DENIED, and FAILED envelopes are persisted but NOT
        delivered. The three-way distinction between TOPOLOGY_DENIED
        (structural), POLICY_DENIED (policy-rule authorisation), and
        DENIED (operational governance) is preserved on the envelope
        status — Sprint L3 final directive.
        """
        return self.status in {
            CoordinationStatus.DISPATCHED,
            CoordinationStatus.DEGRADED,
        }


__all__ = ["CoordinationEnvelope"]
