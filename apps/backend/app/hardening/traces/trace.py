"""`HardeningTrace` — one trace per hardening-runtime call."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.hardening.enums import HardeningTraceKind
from app.hardening.identity import HardeningTraceId


@dataclass(frozen=True, slots=True)
class HardeningTraceContext:
    """Lineage handles propagated through a hardening call."""

    kind: HardeningTraceKind
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    audit_seed: str | None = None


@dataclass(frozen=True, slots=True)
class HardeningTrace:
    """Apex trace for one hardening-runtime call."""

    trace_id: HardeningTraceId
    kind: HardeningTraceKind
    runtime_instance_id: uuid.UUID
    sequence: int
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    audit_seed: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])
    tenant_authority_source: str | None = None


__all__ = ["HardeningTrace", "HardeningTraceContext"]
