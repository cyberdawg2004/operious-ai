"""`SessionTrace` / `SessionTraceContext` — one trace per runtime call.

Mirrors the discipline of every sibling substrate. The trace
carries deterministic ordering metadata, lineage handles, and
operation classification.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping

from app.session.identity import (
    SessionEventId,
    SessionId,
    SessionReconstructionId,
    SessionTraceId,
)


class SessionTraceKind(StrEnum):
    """Classification of which runtime call this trace describes."""

    OPEN_SESSION = "open_session"
    APPEND_EVENT = "append_event"
    RECORD_LIFECYCLE = "record_lifecycle"
    RECORD_CONTEXT = "record_context"
    RECORD_CORRELATION = "record_correlation"
    RECONSTRUCT = "reconstruct"
    LOOKUP = "lookup"


@dataclass(frozen=True, slots=True)
class SessionTraceContext:
    """Lineage identifiers propagated through a session call."""

    kind: SessionTraceKind
    session_id: SessionId | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    principal_id: str | None = None


@dataclass(frozen=True, slots=True)
class SessionTrace:
    """Apex trace for one session-runtime call."""

    trace_id: SessionTraceId
    kind: SessionTraceKind
    runtime_instance_id: uuid.UUID
    sequence: int
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    session_id: SessionId | None = None
    event_id: SessionEventId | None = None
    reconstruction_id: SessionReconstructionId | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    principal_id: str | None = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    tenant_authority_source: str | None = None
    # 2.5-G3: governance join axes — same pattern as
    # ``CoordinationEnvelope`` / ``BoundaryTrace`` /
    # ``ArbitrationTrace``. ID-only; session substrate never imports
    # governance internals. Replay tools join by id against the
    # governance repository instead of re-evaluating.
    governance_decision_id: uuid.UUID | None = None
    governance_chain_id: str | None = None


__all__ = [
    "SessionTrace",
    "SessionTraceContext",
    "SessionTraceKind",
]
