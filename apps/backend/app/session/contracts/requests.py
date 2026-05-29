"""Typed runtime requests.

Six request shapes, one per runtime method:

* `OpenSessionRequest`         — `runtime.open_session()`
* `AppendEventRequest`         — `runtime.append_event()`
* `RecordLifecycleRequest`     — `runtime.record_lifecycle()`
* `RecordContextRequest`       — `runtime.record_context()`
* `RecordCorrelationRequest`   — `runtime.record_correlation()`
* `ReconstructSessionRequest`  — `runtime.reconstruct()`

All requests are immutable. Lineage / correlation handles propagate
through every shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.identity import (
    AuthorityContext,
    check_tenant_authority_coexistence,
)
from app.session.enums import (
    SessionContinuityMode,
    SessionCorrelationKind,
    SessionEventKind,
    SessionLifecyclePhase,
    SessionScope,
)
from app.session.identity import SessionId
from app.session.models.context import SessionContext


@dataclass(frozen=True, slots=True)
class OpenSessionRequest:
    """Open a new operational session.

    Attributes:
        scope:               Authority/scoping classification.
        external_handle:     Caller-supplied opaque anchor.
        tenant_id:           Tenant identifier.
        principal_id:        Principal identifier.
        parent_session_id:   Optional parent session id.
        context:             Optional initial context.
        opened_at_override:  Caller-pinned `opened_at` for replay-
                              equivalent reconstruction.
        session_id_override: Caller-pinned `SessionId` for replay-
                              equivalent reconstruction.
        correlation_id:      Lineage continuity handle.
        request_id:          Per-call lineage handle.
        metadata:            Free-form, propagated.
    """

    scope: SessionScope
    external_handle: str
    tenant_id: str | None = None
    principal_id: str | None = None
    parent_session_id: SessionId | None = None
    context: SessionContext | None = None
    opened_at_override: datetime | None = None
    session_id_override: SessionId | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])
    authority: AuthorityContext | None = None

    def __post_init__(self) -> None:
        check_tenant_authority_coexistence(
            contract_name="OpenSessionRequest",
            authority=self.authority,
            tenant_id=self.tenant_id,
        )


@dataclass(frozen=True, slots=True)
class AppendEventRequest:
    """Append one timeline event to a session.

    Attributes:
        session_id:        Target session.
        kind:              Classification of the event.
        continuity_mode:   How the event entered the timeline.
        occurred_at:       Wall-clock timestamp of the underlying
                            observation.
        payload:           Canonicalisation-safe audit payload.
                            The substrate canonicalises before
                            persistence.
        annotation:        Free-form annotation.
        external_correlation_id: Optional sibling-substrate
                            correlation handle.
        correlation_id:    Lineage continuity handle.
        request_id:        Per-call lineage handle.
        idempotency_key:   Optional replay-stable key. When supplied,
                           the session runtime returns the original
                           event for duplicate appends instead of
                           advancing chronology.
        metadata:          Free-form, propagated.
    """

    session_id: SessionId
    kind: SessionEventKind
    occurred_at: datetime
    continuity_mode: SessionContinuityMode = (
        SessionContinuityMode.SYNCHRONOUS
    )
    payload: Mapping[str, Any] = field(default_factory=dict[str, Any])
    annotation: str | None = None
    external_correlation_id: str | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    idempotency_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def __post_init__(self) -> None:
        if self.idempotency_key is None:
            return
        if (
            not self.idempotency_key
            or len(self.idempotency_key) > 255
        ):
            raise ValueError(
                "AppendEventRequest.idempotency_key must be a "
                "non-empty string of at most 255 characters"
            )


@dataclass(frozen=True, slots=True)
class RecordLifecycleRequest:
    """Record an explicit lifecycle classification.

    Attributes:
        session_id:        Target session.
        phase:             New classification.
        reason:            Optional human-readable annotation.
        recorded_at:       Caller-pinned timestamp; defaults to
                            now() when ``None``.
        correlation_id:    Lineage continuity handle.
        request_id:        Per-call lineage handle.
        metadata:          Free-form, propagated.
    """

    session_id: SessionId
    phase: SessionLifecyclePhase
    reason: str | None = None
    recorded_at: datetime | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class RecordContextRequest:
    """Bind / replace the session context.

    The substrate keeps the previous context in the timeline
    (CONTEXT_ATTACHED event) so historical reconstruction can
    rebuild the context state at any prior point.
    """

    session_id: SessionId
    context: SessionContext
    recorded_at: datetime | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class RecordCorrelationRequest:
    """Record a cross-substrate correlation observation.

    The substrate appends a CORRELATION_RECORDED timeline event
    with the correlation handle attached.
    """

    session_id: SessionId
    kind: SessionCorrelationKind
    external_id: str
    external_correlation_id: str | None = None
    annotation: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict[str, Any])
    recorded_at: datetime | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class ReconstructSessionRequest:
    """Reconstruct a session's continuity state.

    Attributes:
        session_id:           Target session.
        as_of:                Optional inclusive upper-bound on
                               `occurred_at`. Events after this
                               instant are excluded.
        from_sequence:        Optional inclusive lower-bound on
                               event sequence.
        to_sequence:          Optional inclusive upper-bound on
                               event sequence.
        include_lineage:      When True, populate the `lineage`
                               field of the result.
        include_correlations: When True, populate the
                               `correlations` field of the result.
        correlation_id:       Lineage continuity handle.
        request_id:           Per-call lineage handle.
        metadata:             Free-form, propagated.
    """

    session_id: SessionId
    as_of: datetime | None = None
    from_sequence: int | None = None
    to_sequence: int | None = None
    include_lineage: bool = True
    include_correlations: bool = True
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


__all__ = [
    "AppendEventRequest",
    "OpenSessionRequest",
    "ReconstructSessionRequest",
    "RecordContextRequest",
    "RecordCorrelationRequest",
    "RecordLifecycleRequest",
]
