"""Operious AI — Operational Session Runtime (Sprint N).

Continuity-only ledger. The substrate's responsibilities:

* preserve continuity identity (`OperationalSession`),
* maintain an append-only timeline of immutable, classification-
  tagged events (`SessionTimelineEvent` / `SessionTimeline`),
* preserve immutable ancestry (`SessionLineage`),
* record explicit lifecycle classifications (`SessionLifecycle`),
* record cross-substrate correlation observations
  (`SessionCorrelation`),
* enable byte-stable historical reconstruction
  (`SessionReconstructor`).

What this substrate IS NOT (and never will be):

* a workflow engine,
* an orchestration runtime,
* a planner / agent dispatcher,
* an event bus / pub-sub,
* a retry / scheduling system,
* a state machine.

Substrate-isolation discipline:

The session substrate intentionally does NOT import from any
sibling-substrate runtime (governance, agents, supervisor,
coordination, arbitration, memory, embeddings, replay, tracing,
boundary). Cross-substrate references are recorded as opaque
``(kind, external_id)`` pairs via `SessionCorrelation`. This
containment is asserted in `tests/test_session_invariants.py`.
"""

from app.session.contracts import (
    AppendEventRequest,
    AppendEventResult,
    OpenSessionRequest,
    OpenSessionResult,
    ReconstructSessionRequest,
    ReconstructSessionResult,
    RecordContextRequest,
    RecordContextResult,
    RecordCorrelationRequest,
    RecordCorrelationResult,
    RecordLifecycleRequest,
    RecordLifecycleResult,
)
from app.session.correlation.correlator import build_correlation
from app.session.envelopes import SessionEnvelope
from app.session.enums import (
    SessionContinuityMode,
    SessionCorrelationKind,
    SessionEventKind,
    SessionLifecyclePhase,
    SessionReconstructionStatus,
    SessionScope,
)
from app.session.exceptions import (
    SessionConfigurationError,
    SessionError,
    SessionLifecycleError,
    SessionLineageError,
    SessionNotFoundError,
    SessionPersistenceError,
    SessionReconstructionError,
    SessionValidationError,
)
from app.session.identity import (
    SessionCorrelationId,
    SessionEventId,
    SessionId,
    SessionLineageId,
    SessionReconstructionId,
    SessionTraceId,
    as_correlation_id,
    as_event_id,
    as_lineage_id,
    as_session_id,
    derive_correlation_id,
    derive_event_id,
    derive_lineage_id,
    derive_reconstruction_id,
    derive_session_id,
    derive_trace_id,
    generate_correlation_id,
    generate_event_id,
    generate_lineage_id,
    generate_reconstruction_id,
    generate_session_id,
    generate_trace_id,
)
from app.session.lifecycle.classifier import (
    LIFECYCLE_PHASES_TERMINAL,
    is_terminal,
    next_phase_classification,
)
from app.session.lineage.tracker import (
    build_lineage_for_child,
    build_lineage_for_root,
    extend_lineage,
)
from app.session.models import (
    OperationalSession,
    SessionContext,
    SessionCorrelation,
    SessionIdentity,
    SessionLifecycle,
    SessionLineage,
    SessionTimeline,
    SessionTimelineEvent,
)
from app.session.persistence import (
    InMemorySessionPersistence,
    SessionCorrelationQuery,
    SessionCorrelationRecord,
    SessionEventQuery,
    SessionEventRecord,
    SessionPersistenceProtocol,
    SessionQuery,
    SessionRecord,
    SessionRecordPage,
)
from app.session.reconstruction.reconstructor import (
    SessionReconstructor,
)
from app.session.registry.registry import SessionRegistry
from app.session.runtime.runtime import SessionRuntime
from app.session.serializers.canonical import (
    canonicalize_attributes,
    canonicalize_payload,
    content_fingerprint,
    serialize_correlation,
    serialize_session,
    serialize_timeline_event,
)
from app.session.taxonomy import SessionMetadataKey
from app.session.timeline.builder import (
    append_event,
    build_event,
    build_timeline,
)
from app.session.traces.trace import (
    SessionTrace,
    SessionTraceContext,
    SessionTraceKind,
)


__all__ = [
    # Enums
    "SessionContinuityMode",
    "SessionCorrelationKind",
    "SessionEventKind",
    "SessionLifecyclePhase",
    "SessionReconstructionStatus",
    "SessionScope",
    # Exceptions
    "SessionConfigurationError",
    "SessionError",
    "SessionLifecycleError",
    "SessionLineageError",
    "SessionNotFoundError",
    "SessionPersistenceError",
    "SessionReconstructionError",
    "SessionValidationError",
    # Identity
    "SessionCorrelationId",
    "SessionEventId",
    "SessionId",
    "SessionLineageId",
    "SessionReconstructionId",
    "SessionTraceId",
    "as_correlation_id",
    "as_event_id",
    "as_lineage_id",
    "as_session_id",
    "derive_correlation_id",
    "derive_event_id",
    "derive_lineage_id",
    "derive_reconstruction_id",
    "derive_session_id",
    "derive_trace_id",
    "generate_correlation_id",
    "generate_event_id",
    "generate_lineage_id",
    "generate_reconstruction_id",
    "generate_session_id",
    "generate_trace_id",
    # Taxonomy
    "SessionMetadataKey",
    # Models
    "OperationalSession",
    "SessionContext",
    "SessionCorrelation",
    "SessionIdentity",
    "SessionLifecycle",
    "SessionLineage",
    "SessionTimeline",
    "SessionTimelineEvent",
    # Contracts
    "AppendEventRequest",
    "AppendEventResult",
    "OpenSessionRequest",
    "OpenSessionResult",
    "ReconstructSessionRequest",
    "ReconstructSessionResult",
    "RecordContextRequest",
    "RecordContextResult",
    "RecordCorrelationRequest",
    "RecordCorrelationResult",
    "RecordLifecycleRequest",
    "RecordLifecycleResult",
    # Envelope + tracing
    "SessionEnvelope",
    "SessionTrace",
    "SessionTraceContext",
    "SessionTraceKind",
    # Lifecycle helpers
    "LIFECYCLE_PHASES_TERMINAL",
    "is_terminal",
    "next_phase_classification",
    # Lineage helpers
    "build_lineage_for_child",
    "build_lineage_for_root",
    "extend_lineage",
    # Timeline helpers
    "append_event",
    "build_event",
    "build_timeline",
    # Correlation helpers
    "build_correlation",
    # Serialisation helpers
    "canonicalize_attributes",
    "canonicalize_payload",
    "content_fingerprint",
    "serialize_correlation",
    "serialize_session",
    "serialize_timeline_event",
    # Persistence
    "InMemorySessionPersistence",
    "SessionCorrelationQuery",
    "SessionCorrelationRecord",
    "SessionEventQuery",
    "SessionEventRecord",
    "SessionPersistenceProtocol",
    "SessionQuery",
    "SessionRecord",
    "SessionRecordPage",
    # Reconstruction
    "SessionReconstructor",
    # Registry
    "SessionRegistry",
    # Runtime
    "SessionRuntime",
]
