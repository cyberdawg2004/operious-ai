"""Query / page models for the session persistence repository."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.session.enums import (
    SessionCorrelationKind,
    SessionEventKind,
    SessionLifecyclePhase,
    SessionScope,
)
from app.session.identity import (
    SessionCorrelationId,
    SessionEventId,
    SessionId,
)
from app.session.persistence.records import (
    SessionCorrelationRecord,
    SessionEventRecord,
    SessionRecord,
)


@dataclass(frozen=True, slots=True)
class SessionQuery:
    """Filter parameters for session listing."""

    session_id: SessionId | None = None
    scope: SessionScope | None = None
    tenant_id: str | None = None
    principal_id: str | None = None
    external_handle: str | None = None
    lifecycle_phase: SessionLifecyclePhase | None = None
    limit: int | None = None
    offset: int = 0


@dataclass(frozen=True, slots=True)
class SessionEventQuery:
    """Filter parameters for timeline-event listing."""

    session_id: SessionId
    event_id: SessionEventId | None = None
    kind: SessionEventKind | None = None
    from_sequence: int | None = None
    to_sequence: int | None = None
    occurred_before_or_at: datetime | None = None
    occurred_after_or_at: datetime | None = None
    limit: int | None = None
    offset: int = 0


@dataclass(frozen=True, slots=True)
class SessionCorrelationQuery:
    """Filter parameters for correlation-record listing."""

    session_id: SessionId | None = None
    correlation_id: SessionCorrelationId | None = None
    kind: SessionCorrelationKind | None = None
    external_id: str | None = None
    limit: int | None = None
    offset: int = 0


@dataclass(frozen=True, slots=True)
class SessionRecordPage:
    """Paginated repository response (deterministically ordered).

    One of `sessions` / `events` / `correlations` is populated;
    the others are empty.
    """

    sessions: tuple[SessionRecord, ...] = ()
    events: tuple[SessionEventRecord, ...] = ()
    correlations: tuple[SessionCorrelationRecord, ...] = ()
    total: int = 0


__all__ = [
    "SessionCorrelationQuery",
    "SessionEventQuery",
    "SessionQuery",
    "SessionRecordPage",
]
