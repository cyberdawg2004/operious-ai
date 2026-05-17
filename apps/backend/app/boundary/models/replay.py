"""`BoundaryReplayRecord` — one observed replay event.

The replay record is what the `BoundaryIdempotencyRegistry`
stores. It pins:

* the deterministic `replay_key`,
* the original `event_id` (set the first time the key was seen),
* a fingerprint of the canonical payload (used to detect
  ``LINEAGE_DRIFT``).

The substrate NEVER mutates a replay record. Subsequent deliveries
add new audit observations alongside it; the original record is
preserved verbatim for replay reconstruction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.boundary.enums import (
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.identity import BoundaryEventId


@dataclass(frozen=True, slots=True)
class BoundaryReplayRecord:
    """One stored replay observation.

    Attributes:
        replay_key:           Deterministic UUID5 derived from
                               external coordinates. Primary index.
        event_id:             The `BoundaryEventId` first
                               assigned to this replay key.
        source_type:          Canonical source classification.
        external_message_id:  Original external id.
        tenant_id:            Tenant scope.
        content_fingerprint:  Stable hash of the canonical payload
                               (hex string). Used to compare new
                               deliveries for drift.
        first_seen_at:        Wall-clock timestamp of first
                               observation.
        last_seen_at:         Wall-clock timestamp of most recent
                               observation. The registry MAY rebuild
                               the record with an updated
                               `last_seen_at`; the original
                               `event_id` and `first_seen_at`
                               NEVER change.
        observation_count:    Total observations of this replay
                               key, including the original.
        last_disposition:     Disposition assigned at the most
                               recent observation.
        metadata:             Free-form audit payload.
    """

    replay_key: uuid.UUID
    event_id: BoundaryEventId
    source_type: BoundarySourceType
    external_message_id: str
    tenant_id: str | None
    content_fingerprint: str
    first_seen_at: datetime
    last_seen_at: datetime
    observation_count: int = 1
    last_disposition: BoundaryReplayDisposition = (
        BoundaryReplayDisposition.NEW
    )
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["BoundaryReplayRecord"]
