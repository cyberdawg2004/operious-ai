"""`BoundaryIngressResult` / `BoundaryEgressResult` — typed outputs."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.boundary.enums import (
    BoundaryDirection,
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
)
from app.boundary.identity import (
    BoundaryEgressId,
    BoundaryEventId,
    BoundaryIngressId,
)
from app.boundary.models.event import ExternalBoundaryEvent
from app.boundary.models.normalization import (
    BoundaryNormalizationResult,
)
from app.boundary.models.payload import EgressPayload


@dataclass(frozen=True, slots=True)
class BoundaryIngressResult:
    """Apex result of one ingest() call.

    Attributes:
        ingress_id:             Stable per-call identifier.
        event_id:               Deterministic event id derived
                                 from external coordinates. May be
                                 ``None`` when normalisation
                                 produced no valid id (e.g.
                                 malformed payload).
        direction:              Always INGRESS.
        normalization:          Adapter normalisation result.
        replay_disposition:     Replay-detection classification.
        replay_key:             Deterministic replay key
                                 (registry primary index).
        original_event_id:      The first `BoundaryEventId` ever
                                 observed for this replay key.
                                 Equals `event_id` for NEW.
        event:                  Canonical event built when
                                 normalisation succeeded.
                                 ``None`` for failed paths.
        adapter_name:           Adapter that handled the payload.
        sequence:               Monotonic per-runtime-instance.
        runtime_instance_id:    Stable runtime instance id.
        correlation_id /
        request_id /
        tenant_id:              Lineage handles.
        started_at / ended_at:  Wall-clock window.
        latency_ms:             Total ingest latency.
        error:                  Set when the framework itself
                                 failed (adapter raised, persistence
                                 failed). Distinct from
                                 normalisation status.
        metadata:               Free-form, propagated.
    """

    ingress_id: BoundaryIngressId
    direction: BoundaryDirection
    normalization: BoundaryNormalizationResult
    replay_disposition: BoundaryReplayDisposition
    replay_key: uuid.UUID | None
    adapter_name: str
    sequence: int
    runtime_instance_id: uuid.UUID
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    event_id: BoundaryEventId | None = None
    original_event_id: BoundaryEventId | None = None
    event: ExternalBoundaryEvent | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_normalised(self) -> bool:
        return (
            self.normalization.status
            is BoundaryNormalizationStatus.OK
        )

    @property
    def is_replay(self) -> bool:
        return self.replay_disposition is not (
            BoundaryReplayDisposition.NEW
        ) and self.replay_disposition is not (
            BoundaryReplayDisposition.INVALID_KEY
        )

    @property
    def is_drift(self) -> bool:
        return (
            self.replay_disposition
            is BoundaryReplayDisposition.LINEAGE_DRIFT
        )


@dataclass(frozen=True, slots=True)
class BoundaryEgressResult:
    """Apex result of one emit() call.

    Attributes:
        egress_id:              Stable per-call identifier.
        direction:              Always EGRESS.
        adapter_name:           Adapter that translated the artifact.
        payload:                Resulting outbound payload.
                                 ``None`` when adapter failed.
        sequence:               Monotonic per-runtime-instance.
        runtime_instance_id:    Stable runtime instance id.
        translated_at:          Wall-clock translation timestamp.
        correlation_id /
        request_id /
        tenant_id:              Lineage handles.
        governance_decision_id: Persisted ALLOW decision that
                                 authorized this egress.
        started_at / ended_at:  Wall-clock window.
        latency_ms:             Total emit latency.
        error:                  Set when the framework itself
                                 failed.
        metadata:               Free-form, propagated.
    """

    egress_id: BoundaryEgressId
    direction: BoundaryDirection
    adapter_name: str
    sequence: int
    runtime_instance_id: uuid.UUID
    translated_at: datetime
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    payload: EgressPayload | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    governance_decision_id: uuid.UUID | None = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_translated(self) -> bool:
        return self.payload is not None and self.error is None


__all__ = ["BoundaryIngressResult", "BoundaryEgressResult"]
