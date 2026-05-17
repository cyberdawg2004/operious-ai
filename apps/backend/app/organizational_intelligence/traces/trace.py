"""`IntelligenceTrace` — one trace per intelligence-runtime call."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.organizational_intelligence.enums import (
    IntelligenceTraceKind,
)
from app.organizational_intelligence.identity import (
    IntelligenceTraceId,
)


@dataclass(frozen=True, slots=True)
class IntelligenceTraceContext:
    """Lineage handles propagated through an intelligence call."""

    kind: IntelligenceTraceKind
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    source_session_id: str | None = None
    source_boundary_event_id: str | None = None
    source_supervisor_evaluation_id: str | None = None
    source_governance_evaluation_id: str | None = None


@dataclass(frozen=True, slots=True)
class IntelligenceTrace:
    """Apex trace for one intelligence-runtime call."""

    trace_id: IntelligenceTraceId
    kind: IntelligenceTraceKind
    runtime_instance_id: uuid.UUID
    sequence: int
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    source_session_id: str | None = None
    source_boundary_event_id: str | None = None
    source_supervisor_evaluation_id: str | None = None
    source_governance_evaluation_id: str | None = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = [
    "IntelligenceTrace",
    "IntelligenceTraceContext",
]
