"""Persistence records — frozen, slotted, JSON-serialisable."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.boundary.enums import (
    BoundaryDirection,
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.identity import (
    BoundaryEgressId,
    BoundaryEventId,
    BoundaryIngressId,
)


@dataclass(frozen=True, slots=True)
class BoundaryIngressRecord:
    """Persistence shape of one ingest() outcome."""

    ingress_id: BoundaryIngressId
    direction: BoundaryDirection
    runtime_instance_id: uuid.UUID
    sequence: int
    source_type: BoundarySourceType
    source_id: str
    tenant_id: str | None
    adapter_name: str
    normalization_status: BoundaryNormalizationStatus
    message_type: BoundaryMessageType
    replay_disposition: BoundaryReplayDisposition
    replay_key: uuid.UUID | None
    event_id: BoundaryEventId | None
    original_event_id: BoundaryEventId | None
    external_message_id: str | None
    external_conversation_id: str | None
    external_emitted_at: datetime | None
    received_at: datetime
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    correlation_id: str | None
    request_id: str | None
    canonical_payload: Mapping[str, Any]
    error: str | None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BoundaryEgressRecord:
    """Persistence shape of one emit() outcome."""

    egress_id: BoundaryEgressId
    direction: BoundaryDirection
    runtime_instance_id: uuid.UUID
    sequence: int
    source_type: BoundarySourceType
    source_id: str
    tenant_id: str | None
    adapter_name: str
    payload_body: Any
    payload_content_type: str | None
    payload_target_uri: str | None
    payload_method: str | None
    payload_headers: Mapping[str, str]
    translated_at: datetime
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    correlation_id: str | None
    request_id: str | None
    error: str | None
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["BoundaryIngressRecord", "BoundaryEgressRecord"]
