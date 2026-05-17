"""Typed runtime results.

Each request shape pairs with a result shape. All results carry
the apex artifact produced by the call plus deterministic
lineage handles.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.session.enums import (
    SessionEventKind,
    SessionReconstructionStatus,
)
from app.session.identity import (
    SessionCorrelationId,
    SessionEventId,
    SessionId,
    SessionReconstructionId,
)
from app.session.models.correlation import SessionCorrelation
from app.session.models.lineage import SessionLineage
from app.session.models.session import OperationalSession
from app.session.models.timeline import SessionTimeline
from app.session.models.timeline_event import (
    SessionTimelineEvent,
)


@dataclass(frozen=True, slots=True)
class _BaseResult:
    """Shared lineage handles for every result shape."""

    sequence: int
    runtime_instance_id: uuid.UUID
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OpenSessionResult(_BaseResult):
    """Outcome of `runtime.open_session()`.

    Attributes:
        session: The newly created `OperationalSession`. ``None``
                  only when an internal validation failed and the
                  envelope-level `error` is populated.
    """

    session: OperationalSession | None = None


@dataclass(frozen=True, slots=True)
class AppendEventResult(_BaseResult):
    """Outcome of `runtime.append_event()`."""

    event: SessionTimelineEvent | None = None
    session: OperationalSession | None = None


@dataclass(frozen=True, slots=True)
class RecordLifecycleResult(_BaseResult):
    """Outcome of `runtime.record_lifecycle()`."""

    event: SessionTimelineEvent | None = None
    session: OperationalSession | None = None


@dataclass(frozen=True, slots=True)
class RecordContextResult(_BaseResult):
    """Outcome of `runtime.record_context()`."""

    event: SessionTimelineEvent | None = None
    session: OperationalSession | None = None


@dataclass(frozen=True, slots=True)
class RecordCorrelationResult(_BaseResult):
    """Outcome of `runtime.record_correlation()`."""

    correlation: SessionCorrelation | None = None
    event: SessionTimelineEvent | None = None
    session: OperationalSession | None = None


@dataclass(frozen=True, slots=True)
class ReconstructSessionResult(_BaseResult):
    """Outcome of `runtime.reconstruct()`.

    Attributes:
        reconstruction_id: Stable per-call identifier (UUID5
                            derivable from
                            ``(session_id, as_of, from, to)``).
        status:             Reconstruction outcome classification.
        session:            Reconstructed `OperationalSession` at
                            the requested instant. ``None`` when
                            status is NOT_FOUND / ERROR.
        timeline:           Reconstructed timeline (may be empty
                            when filters exclude all events).
        lineage:            Reconstructed lineage when
                            `include_lineage` was true.
        correlations:       Reconstructed correlations when
                            `include_correlations` was true.
    """

    reconstruction_id: SessionReconstructionId | None = None
    status: SessionReconstructionStatus = (
        SessionReconstructionStatus.PRISTINE
    )
    session: OperationalSession | None = None
    timeline: SessionTimeline | None = None
    lineage: SessionLineage | None = None
    correlations: tuple[SessionCorrelation, ...] = ()


# Re-exports for typing consumers
SessionEventId  # noqa: B018
SessionId  # noqa: B018
SessionCorrelationId  # noqa: B018
SessionEventKind  # noqa: B018


__all__ = [
    "AppendEventResult",
    "OpenSessionResult",
    "ReconstructSessionResult",
    "RecordContextResult",
    "RecordCorrelationResult",
    "RecordLifecycleResult",
]
