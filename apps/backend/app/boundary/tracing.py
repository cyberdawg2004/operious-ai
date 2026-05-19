"""Boundary traces.

Same discipline as every sibling substrate.

* `BoundaryTraceContext` — identity bundle propagated into / out
                            of an ingest/emit call.
* `BoundaryTrace`        — one per call. Pairs 1:1 with the
                            corresponding result.

The boundary trace deliberately preserves both the
**internal-substrate** lineage (correlation_id / request_id /
tenant_id) AND the **external-source** lineage
(source_type / source_id / external_message_id /
external_conversation_id) so audit consumers can reconstruct the
full path from external delivery to internal artifact.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.boundary.enums import (
    BoundaryDirection,
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
class BoundaryTraceContext:
    """Lineage identifiers propagated through a boundary call."""

    direction: BoundaryDirection
    source_type: BoundarySourceType
    source_id: str
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    external_message_id: str | None = None
    external_conversation_id: str | None = None


@dataclass(frozen=True, slots=True)
class BoundaryTrace:
    """Apex trace for one boundary call.

    The trace is direction-aware: `event_id` and replay fields
    are populated for INGRESS only; `egress_id` is populated for
    EGRESS only.
    """

    direction: BoundaryDirection
    runtime_instance_id: uuid.UUID
    sequence: int
    source_type: BoundarySourceType
    source_id: str
    adapter_name: str
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    external_message_id: str | None = None
    external_conversation_id: str | None = None
    # INGRESS-specific
    ingress_id: BoundaryIngressId | None = None
    event_id: BoundaryEventId | None = None
    normalization_status: BoundaryNormalizationStatus | None = None
    replay_disposition: BoundaryReplayDisposition | None = None
    # EGRESS-specific
    egress_id: BoundaryEgressId | None = None
    error: str | None = None
    # 2.5-G1 ⇒ 2.75-δ: governance provenance was originally added
    # here mirroring the ``CoordinationEnvelope`` pattern, but the
    # apex boundary substrate (``BoundaryIngressRuntime`` /
    # ``BoundaryEgressRuntime``) holds no governance gate of its
    # own — it is the pure protocol translator. Per the doctrine
    # "schema-without-data is worse than absence" the fields were
    # removed in Wedge 2.75-δ. Governance-attributed boundary
    # operations live in the translation/voice substrates whose
    # traces (``TranslationTrace`` / ``VoiceTrace``) project the
    # capability-gate verdict directly. A future wedge that adds
    # an apex boundary governance pre-flight should re-introduce
    # the fields at that point — not before.
    # 2.75-β: authority-resolution provenance. Records which input
    # axis the effective ``tenant_id`` came from
    # (``typed_authority`` / ``legacy_tenant`` / ``observed_tenant``
    # / ``none``). Mirrors the analogous fields on coordination,
    # supervisor, arbitration, and session traces — auditors join on
    # tenant_authority_source to reconstruct the attribution chain
    # across every substrate that processed a request.
    tenant_authority_source: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["BoundaryTraceContext", "BoundaryTrace"]
