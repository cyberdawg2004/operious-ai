"""Query models + paginated result for the boundary persistence repo."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.boundary.enums import (
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.identity import (
    BoundaryEgressId,
    BoundaryEventId,
    BoundaryIngressId,
)
from app.boundary.persistence.records import (
    BoundaryEgressRecord,
    BoundaryIngressRecord,
)


@dataclass(frozen=True, slots=True)
class BoundaryIngressQuery:
    """Filter parameters for ingress-record listing.

    Multiple filters AND together. ``None`` means "no constraint".
    """

    ingress_id: BoundaryIngressId | None = None
    event_id: BoundaryEventId | None = None
    replay_key: uuid.UUID | None = None
    source_type: BoundarySourceType | None = None
    normalization_status: BoundaryNormalizationStatus | None = None
    replay_disposition: BoundaryReplayDisposition | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    limit: int | None = None
    offset: int = 0


@dataclass(frozen=True, slots=True)
class BoundaryEgressQuery:
    """Filter parameters for egress-record listing."""

    egress_id: BoundaryEgressId | None = None
    source_type: BoundarySourceType | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    limit: int | None = None
    offset: int = 0


@dataclass(frozen=True, slots=True)
class BoundaryRecordPage:
    """Paginated repository response (deterministically ordered).

    Either ``ingress`` or ``egress`` is populated, never both.
    """

    ingress: tuple[BoundaryIngressRecord, ...] = ()
    egress: tuple[BoundaryEgressRecord, ...] = ()
    total: int = 0


__all__ = [
    "BoundaryEgressQuery",
    "BoundaryIngressQuery",
    "BoundaryRecordPage",
]
