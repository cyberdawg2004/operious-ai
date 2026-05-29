"""`ExternalBoundaryEvent` — the canonical inbound event.

This is the apex value object the boundary substrate produces
from one ingest. It pairs the deterministic `BoundaryEventId`
with the canonical fields extracted by the adapter.

Two webhook deliveries that share
``(source_type, external_message_id, tenant_id)`` produce
`ExternalBoundaryEvent`s with byte-identical `event_id`s. That is
the foundation of replay-safe ingestion.

The event is **immutable**. Re-deliveries do NOT mutate prior
events; the substrate surfaces a `BoundaryReplayDisposition`
classification instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.boundary.enums import BoundaryMessageType
from app.boundary.identity import (
    BoundaryEventId,
    ExternalConversationId,
    ExternalMessageId,
)
from app.boundary.models.source import BoundarySource


@dataclass(frozen=True, slots=True)
class ExternalBoundaryEvent:
    """Canonical, immutable inbound event.

    Attributes:
        event_id:                Deterministic UUID5 derived from
                                  external coordinates.
        source:                   `BoundarySource` describing the
                                  emitting endpoint.
        message_type:             Canonical message type.
        external_message_id:      Stable id within the external
                                  system (typed wrapper).
        external_conversation_id: Stable conversation id
                                  (typed wrapper). ``None`` for
                                  events that aren't conversational.
        canonical_payload:        Normalised payload, canonical-
                                  ordered. Used for replay-drift
                                  detection and audit.
        received_at:              Wall-clock timestamp when the
                                  substrate received the event.
        external_emitted_at:      Wall-clock timestamp the external
                                  system reported the event.
                                  ``None`` when not provided.
        adapter_name:             Name of the adapter that
                                  normalised this event.
        metadata:                 Free-form, propagated through
                                  persistence.
    """

    event_id: BoundaryEventId
    source: BoundarySource
    message_type: BoundaryMessageType
    external_message_id: ExternalMessageId
    canonical_payload: Mapping[str, Any]
    received_at: datetime
    external_conversation_id: ExternalConversationId | None = None
    external_emitted_at: datetime | None = None
    adapter_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


__all__ = ["ExternalBoundaryEvent"]
