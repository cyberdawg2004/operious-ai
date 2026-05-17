"""`BoundaryIngressRequest` / `BoundaryEgressRequest` — typed inputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.boundary.identity import (
    BoundaryEgressId,
    BoundaryIngressId,
)
from app.boundary.models.payload import (
    EgressPayload,
    IngressPayload,
)
from app.boundary.models.source import BoundarySource


@dataclass(frozen=True, slots=True)
class BoundaryIngressRequest:
    """Typed input to `BoundaryIngressRuntime.ingest()`.

    Carries the untrusted payload, the declared source, and lineage
    handles (correlation_id, request_id). Adapter selection is
    explicit: the caller names the adapter; the substrate never
    auto-discovers.

    Attributes:
        source:              Declared external endpoint.
        adapter_name:        Name of the registered ingress
                              adapter to invoke.
        payload:             Untrusted raw payload.
        correlation_id:      Lineage continuity handle.
        request_id:          Per-call lineage handle.
        ingress_id_override: Replay aid (caller-pinned id).
        metadata:            Free-form, propagated through
                              persistence.
    """

    source: BoundarySource
    adapter_name: str
    payload: IngressPayload
    correlation_id: str | None = None
    request_id: str | None = None
    ingress_id_override: BoundaryIngressId | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BoundaryEgressRequest:
    """Typed input to `BoundaryEgressRuntime.emit()`.

    The egress request carries an OPAQUE artifact (free-form
    `Any`) plus a typed adapter name. The adapter is responsible
    for understanding the artifact's shape and producing an
    `EgressPayload`. The substrate does NOT inspect the artifact —
    that would couple the boundary to caller-specific runtime
    types, violating substrate isolation.

    Attributes:
        source:              Declared external endpoint.
        adapter_name:        Name of the registered egress adapter.
        artifact:            Opaque caller-supplied artifact the
                              adapter understands.
        prebuilt_payload:    OPTIONAL pre-translated payload. If
                              set, the substrate skips adapter
                              translation and uses this verbatim.
                              Caller is responsible for shape.
        correlation_id:      Lineage continuity handle.
        request_id:          Per-call lineage handle.
        egress_id_override:  Replay aid (caller-pinned id).
        metadata:            Free-form, propagated through
                              persistence.
    """

    source: BoundarySource
    adapter_name: str
    artifact: Any
    prebuilt_payload: EgressPayload | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    egress_id_override: BoundaryEgressId | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = [
    "BoundaryIngressRequest",
    "BoundaryEgressRequest",
]
