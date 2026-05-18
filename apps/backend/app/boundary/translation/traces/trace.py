"""`TranslationTrace` — one trace per translation runtime call."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.boundary.translation.enums import TranslationTraceKind
from app.boundary.translation.identity import TranslationTraceId


@dataclass(frozen=True, slots=True)
class TranslationTraceContext:
    """Context handles propagated through a translation call."""

    kind: TranslationTraceKind
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    seed: str | None = None


@dataclass(frozen=True, slots=True)
class TranslationTrace:
    """Apex trace for one translation-runtime call."""

    trace_id: TranslationTraceId
    kind: TranslationTraceKind
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
    tenant_authority_source: str | None = None


__all__ = [
    "TranslationTrace",
    "TranslationTraceContext",
]
