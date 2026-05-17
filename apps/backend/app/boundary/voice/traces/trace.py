"""`VoiceTrace` — one trace per voice runtime call."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.boundary.voice.enums import VoiceTraceKind
from app.boundary.voice.identity import VoiceTraceId


@dataclass(frozen=True, slots=True)
class VoiceTraceContext:
    """Context handles propagated through a voice call."""

    kind: VoiceTraceKind
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    seed: str | None = None


@dataclass(frozen=True, slots=True)
class VoiceTrace:
    """Apex trace for one voice-runtime call."""

    trace_id: VoiceTraceId
    kind: VoiceTraceKind
    runtime_instance_id: uuid.UUID
    sequence: int
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    seed: str | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    provider_name: str | None = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["VoiceTrace", "VoiceTraceContext"]
