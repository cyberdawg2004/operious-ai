"""Persistence records — frozen, slotted, JSON-serialisable."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.session.enums import (
    SessionContinuityMode,
    SessionCorrelationKind,
    SessionEventKind,
    SessionLifecyclePhase,
    SessionScope,
)
from app.session.identity import (
    SessionCorrelationId,
    SessionEventId,
    SessionId,
    SessionLineageId,
)


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """Apex persistence shape for an `OperationalSession`."""

    session_id: SessionId
    scope: SessionScope
    external_handle: str
    tenant_id: str | None
    principal_id: str | None
    opened_at: datetime
    lifecycle_phase: SessionLifecyclePhase
    lifecycle_recorded_at: datetime
    lifecycle_reason: str | None
    lineage_id: SessionLineageId
    root_session_id: SessionId
    parent_session_id: SessionId | None
    ancestor_session_ids: tuple[SessionId, ...]
    lineage_depth: int
    sequence_head: int
    revision: int
    context_environment: str | None = None
    context_labels: tuple[str, ...] = ()
    context_attributes: Mapping[str, Any] = field(
        default_factory=dict
    )
    context_notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SessionEventRecord:
    """Persistence shape for one timeline event."""

    event_id: SessionEventId
    session_id: SessionId
    sequence: int
    kind: SessionEventKind
    continuity_mode: SessionContinuityMode
    occurred_at: datetime
    recorded_at: datetime
    payload: Mapping[str, Any] = field(default_factory=dict)
    correlation_id: SessionCorrelationId | None = None
    annotation: str | None = None
    # 2.5-G3: governance join axes (mirrors CoordinationRecord).
    governance_decision_id: uuid.UUID | None = None
    governance_chain_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SessionCorrelationRecord:
    """Persistence shape for one correlation observation."""

    correlation_id: SessionCorrelationId
    session_id: SessionId
    kind: SessionCorrelationKind
    external_id: str
    recorded_at: datetime
    external_correlation_id: str | None = None
    annotation: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = [
    "SessionCorrelationRecord",
    "SessionEventRecord",
    "SessionRecord",
]
