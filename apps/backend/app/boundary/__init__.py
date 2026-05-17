"""Operious AI — External Boundary Runtime (Sprint M).

Deterministic translation membrane between the Operious internal
substrates and the external nondeterministic world (webhooks,
streams, REST callbacks, …).

**What this substrate IS**:

* deterministic translation of inbound external deliveries into
  immutable canonical events (`ExternalBoundaryEvent`);
* deterministic translation of outbound runtime artifacts into
  external mutation requests (`EgressPayload`);
* replay-detection infrastructure: duplicate webhook deliveries
  resolve to the SAME deterministic `BoundaryEventId`;
* lineage / source-continuity preserved through every artifact;
* immutable, replay-safe persistence records.

**What this substrate IS NOT** (and never will be):

* webhook orchestration / retry loops;
* delivery-guarantee / queueing infrastructure;
* event bus, Kafka, distributed messaging;
* agent dispatcher / coordination orchestrator;
* autonomous-recovery system.

**Substrate isolation discipline**:

The boundary substrate intentionally does NOT import from any
sibling-substrate runtime (governance, agents, supervisor,
coordination, arbitration, memory, embeddings, replay, tracing).
Callers translate substrate-specific runtime artifacts into
substrate-agnostic egress artifacts (and consume canonical
ingress events) OUTSIDE this package. This containment is asserted
in `tests/test_boundary_invariants.py`.
"""

from app.boundary.adapters import (
    BaseEgressAdapter,
    BaseIngressAdapter,
    TwilioVoiceAdapter,
    WhatsAppWebhookAdapter,
    ZendeskWebhookAdapter,
)
from app.boundary.contracts import (
    BoundaryEgressRequest,
    BoundaryEgressResult,
    BoundaryIngressRequest,
    BoundaryIngressResult,
)
from app.boundary.egress import BoundaryEgressRuntime
from app.boundary.envelopes import (
    BoundaryEgressEnvelope,
    BoundaryIngressEnvelope,
)
from app.boundary.enums import (
    BoundaryDirection,
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.exceptions import (
    BoundaryAuthenticationError,
    BoundaryConfigurationError,
    BoundaryError,
    BoundaryNormalizationError,
    BoundaryPersistenceError,
    BoundaryReplayError,
)
from app.boundary.identity import (
    BoundaryEgressId,
    BoundaryEventId,
    BoundaryIngressId,
    ExternalConversationId,
    ExternalMessageId,
    as_egress_id,
    as_event_id,
    as_external_conversation_id,
    as_external_message_id,
    as_ingress_id,
    derive_egress_id,
    derive_event_id,
    derive_ingress_id,
    derive_replay_key,
    derive_trace_id,
    generate_egress_id,
    generate_event_id,
    generate_ingress_id,
)
from app.boundary.idempotency import (
    BoundaryIdempotencyRegistry,
    BoundaryReplayDecision,
    BoundaryReplayDetector,
)
from app.boundary.ingress import BoundaryIngressRuntime
from app.boundary.models import (
    BoundaryNormalizationResult,
    BoundaryReplayRecord,
    BoundarySource,
    EgressPayload,
    ExternalBoundaryEvent,
    IngressPayload,
)
from app.boundary.normalization import (
    BoundaryNormalizer,
    canonicalize_metadata,
    canonicalize_payload,
    content_fingerprint,
)
from app.boundary.persistence import (
    BoundaryEgressQuery,
    BoundaryEgressRecord,
    BoundaryIngressQuery,
    BoundaryIngressRecord,
    BoundaryPersistenceProtocol,
    BoundaryRecordPage,
    InMemoryBoundaryPersistence,
)
from app.boundary.registry import BoundaryAdapterRegistry
from app.boundary.taxonomy import BoundaryMetadataKey
from app.boundary.tracing import (
    BoundaryTrace,
    BoundaryTraceContext,
)

__all__ = [
    # Enums
    "BoundaryDirection",
    "BoundaryMessageType",
    "BoundaryNormalizationStatus",
    "BoundaryReplayDisposition",
    "BoundarySourceType",
    # Exceptions
    "BoundaryAuthenticationError",
    "BoundaryConfigurationError",
    "BoundaryError",
    "BoundaryNormalizationError",
    "BoundaryPersistenceError",
    "BoundaryReplayError",
    # Identity
    "BoundaryEgressId",
    "BoundaryEventId",
    "BoundaryIngressId",
    "ExternalConversationId",
    "ExternalMessageId",
    "as_egress_id",
    "as_event_id",
    "as_external_conversation_id",
    "as_external_message_id",
    "as_ingress_id",
    "derive_egress_id",
    "derive_event_id",
    "derive_ingress_id",
    "derive_replay_key",
    "derive_trace_id",
    "generate_egress_id",
    "generate_event_id",
    "generate_ingress_id",
    # Taxonomy
    "BoundaryMetadataKey",
    # Models
    "BoundaryNormalizationResult",
    "BoundaryReplayRecord",
    "BoundarySource",
    "EgressPayload",
    "ExternalBoundaryEvent",
    "IngressPayload",
    # Contracts
    "BoundaryEgressRequest",
    "BoundaryEgressResult",
    "BoundaryIngressRequest",
    "BoundaryIngressResult",
    # Envelope + tracing
    "BoundaryEgressEnvelope",
    "BoundaryIngressEnvelope",
    "BoundaryTrace",
    "BoundaryTraceContext",
    # Adapters
    "BaseEgressAdapter",
    "BaseIngressAdapter",
    "TwilioVoiceAdapter",
    "WhatsAppWebhookAdapter",
    "ZendeskWebhookAdapter",
    # Idempotency
    "BoundaryIdempotencyRegistry",
    "BoundaryReplayDecision",
    "BoundaryReplayDetector",
    # Normalisation
    "BoundaryNormalizer",
    "canonicalize_metadata",
    "canonicalize_payload",
    "content_fingerprint",
    # Persistence
    "BoundaryEgressQuery",
    "BoundaryEgressRecord",
    "BoundaryIngressQuery",
    "BoundaryIngressRecord",
    "BoundaryPersistenceProtocol",
    "BoundaryRecordPage",
    "InMemoryBoundaryPersistence",
    # Registry
    "BoundaryAdapterRegistry",
    # Runtimes
    "BoundaryEgressRuntime",
    "BoundaryIngressRuntime",
]
