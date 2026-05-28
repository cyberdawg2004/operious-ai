"""Operational audit event foundation.

A frozen `AuditEvent` dataclass describes the *shape* of every
governance-relevant action the platform takes (orchestration step
started, agent escalation triggered, SOP retrieved, etc.). The
`emit_audit_event` function is the single emission seam.

Today the seam writes through the structured logger so events flow
into the same aggregator as everything else; the shape stays stable
across that transport change. When a dedicated audit pipeline lands
(Sprint G+), this function is the only thing that has to change — call
sites continue to work unmodified.

Explicitly NOT in scope here:

* event buses (Kafka, NATS) — out for Sprint D per the brief
* event sourcing — out for Sprint D per the brief
* persistence of audit rows — comes with the governance sprint
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.logging import get_logger
from app.observability.context import get_request_id
from app.types.json import JsonObject, MetadataMap

_logger = get_logger("audit")


def _empty_json_object() -> JsonObject:
    return {}


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Governance-relevant operational event.

    `actor` identifies who/what initiated the action (`"system"`, an
    agent identifier, a user id once auth lands, etc.). `action` and
    `resource` are short, stable strings — they're what gets queried
    against later, so resist freeform values.
    """

    actor: str
    action: str
    resource: str
    metadata: MetadataMap = field(default_factory=_empty_json_object)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    request_id: str | None = None


def emit_audit_event(event: AuditEvent) -> None:
    """Emit an audit event through the structured logging pipeline.

    `request_id` falls back to the current request context if the
    caller didn't pass one explicitly, so background tasks can still
    record events without bookkeeping.
    """

    payload: dict[str, Any] = {
        "actor": event.actor,
        "action": event.action,
        "resource": event.resource,
        "request_id": event.request_id or get_request_id(),
        "timestamp": event.timestamp.isoformat(),
        "metadata": dict(event.metadata),
    }
    _logger.info("audit_event", extra={"audit": payload})


__all__ = ["AuditEvent", "emit_audit_event"]
