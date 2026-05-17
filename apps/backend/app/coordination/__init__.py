"""Coordination Envelope Foundations — Sprint L1.

`app/coordination/` is the **deterministic communication substrate**
that sits alongside the agent / governance / supervisor runtimes.
It does NOT execute agents, NOT orchestrate workflows, NOT plan, NOT
retry, NOT route autonomously. It mediates every coordination
operation through a single, sequential, replay-safe dispatch path.

Sub-packages and top-level modules — one narrow concern each:

Vocabulary (top-level files):

* `enums`       — `CoordinationStatus`, `CoordinationMessageType`,
                   `CoordinationPriority`, `CoordinationDirection`.
* `identity`    — `CoordinationId`, `CoordinationMessageId`,
                   `CoordinationCorrelationId` + generators /
                   derivers / coercers.
* `taxonomy`    — canonical metadata keys + governance action vocab.
* `tracing`     — `CoordinationTraceContext`, `CoordinationTrace`.
* `envelopes`   — `CoordinationEnvelope` (immutable artifact).
* `exceptions`  — typed coordination exceptions.

Sub-packages:

* `models/`     — internal value objects (payload, recipient,
                   participant).
* `contracts/`  — request / result / message dispatch surface.
* `runtime/`    — `CoordinationRuntime` (apex dispatcher).
* `persistence/`— storage-agnostic record / repository contracts +
                   in-memory reference impl.
* `registry/`   — `CoordinationRegistry` (deterministic participant
                   registry).

Architectural invariants (Sprint L1 RULE 1–7):

* every dispatch is mediated by `CoordinationRuntime` — no agent ↔
  agent direct calls,
* envelopes are immutable runtime artifacts,
* coordination is replay-safe (deterministic identifiers, sequence
  field, byte-stable serialisation),
* sequential / deterministic ordering — no async orchestration
  explosions,
* `CoordinationRuntime` does NOT execute agents, retry, schedule,
  invoke tools, or mutate other runtimes,
* `GovernanceRuntime` is composed, never absorbed,
* supervisors stay read-only — coordination does not write into them.
"""

from app.coordination.contracts import (
    CoordinationDispatchOutcome,
    CoordinationDispatchRequest,
    CoordinationDispatchResult,
    CoordinationMessage,
)
from app.coordination.envelopes import CoordinationEnvelope
from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
    CoordinationPriority,
    CoordinationStatus,
)
from app.coordination.exceptions import (
    CoordinationError,
    CoordinationGovernanceDeniedError,
    CoordinationPersistenceError,
    CoordinationValidationError,
)
from app.coordination.identity import (
    CoordinationCorrelationId,
    CoordinationId,
    CoordinationMessageId,
    as_coordination_id,
    as_correlation_id,
    as_message_id,
    derive_coordination_id,
    derive_correlation_id,
    derive_message_id,
    generate_coordination_id,
    generate_correlation_id,
    generate_message_id,
)
from app.coordination.models import (
    CoordinationParticipant,
    CoordinationPayload,
    CoordinationRecipient,
)
from app.coordination.persistence import (
    CoordinationPersistenceProtocol,
    CoordinationQuery,
    CoordinationRecord,
    InMemoryCoordinationPersistence,
    RecordPage,
    envelope_to_record,
    record_to_envelope,
)
from app.coordination.registry import CoordinationRegistry
from app.coordination.runtime import CoordinationRuntime
from app.coordination.taxonomy import (
    CoordinationGovernanceAction,
    CoordinationMetadataKey,
)
from app.coordination.tracing import (
    CoordinationTrace,
    CoordinationTraceContext,
)

__all__ = [
    # Enums
    "CoordinationStatus",
    "CoordinationMessageType",
    "CoordinationPriority",
    "CoordinationDirection",
    # Identity
    "CoordinationId",
    "CoordinationMessageId",
    "CoordinationCorrelationId",
    "generate_coordination_id",
    "generate_message_id",
    "generate_correlation_id",
    "derive_coordination_id",
    "derive_message_id",
    "derive_correlation_id",
    "as_coordination_id",
    "as_message_id",
    "as_correlation_id",
    # Taxonomy
    "CoordinationMetadataKey",
    "CoordinationGovernanceAction",
    # Tracing
    "CoordinationTraceContext",
    "CoordinationTrace",
    # Models
    "CoordinationPayload",
    "CoordinationRecipient",
    "CoordinationParticipant",
    # Contracts
    "CoordinationMessage",
    "CoordinationDispatchRequest",
    "CoordinationDispatchResult",
    "CoordinationDispatchOutcome",
    # Envelopes
    "CoordinationEnvelope",
    # Exceptions
    "CoordinationError",
    "CoordinationValidationError",
    "CoordinationGovernanceDeniedError",
    "CoordinationPersistenceError",
    # Persistence
    "CoordinationRecord",
    "CoordinationPersistenceProtocol",
    "InMemoryCoordinationPersistence",
    "CoordinationQuery",
    "RecordPage",
    "envelope_to_record",
    "record_to_envelope",
    # Registry
    "CoordinationRegistry",
    # Runtime
    "CoordinationRuntime",
]
