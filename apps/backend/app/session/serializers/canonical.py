"""Canonicalisation + JSON-projection helpers.

Three foundational pure functions:

* `canonicalize_payload(value)`     — recursively re-orders
                                       mappings by sorted key,
                                       canonicalises sequences
                                       and primitives. Output is
                                       JSON-serialisable and
                                       byte-stable.
* `canonicalize_attributes(value)`  — typed wrapper for mappings.
* `content_fingerprint(value)`      — SHA-256 over the canonical
                                       JSON encoding. Used by
                                       reconstruction-drift detection.

Plus three projection helpers that render the apex value objects
into deterministic JSON-friendly dicts:

* `serialize_session(session)`
* `serialize_timeline_event(event)`
* `serialize_correlation(correlation)`

The serialisers are SUBSTRATE-INTERNAL — persistence backends use
them to project records into storage. Sibling substrates that
need cross-substrate audit can also call them, but the substrate
itself never exposes mutable views into the apex objects.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Mapping

from app.session.models.correlation import SessionCorrelation
from app.session.models.session import OperationalSession
from app.session.models.timeline_event import (
    SessionTimelineEvent,
)


_PRIMITIVE_TYPES = (
    str,
    int,
    float,
    bool,
    type(None),
)


def canonicalize_payload(value: Any) -> Any:
    """Recursively normalise into a canonical, JSON-serialisable shape."""
    if isinstance(value, Mapping):
        return {
            key: canonicalize_payload(value[key])
            for key in sorted(value.keys(), key=_string_key)
        }
    if isinstance(value, (list, tuple)):
        return [canonicalize_payload(item) for item in value]
    if isinstance(value, set):
        sorted_items = sorted(
            value, key=lambda x: json.dumps(canonicalize_payload(x))
        )
        return [canonicalize_payload(item) for item in sorted_items]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, _PRIMITIVE_TYPES):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def canonicalize_attributes(
    attributes: Mapping[str, Any],
) -> dict[str, Any]:
    """Canonicalise a metadata mapping (typed wrapper)."""
    if not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]
        attributes, Mapping
    ):
        raise TypeError(
            f"canonicalize_attributes expected a Mapping, got "
            f"{type(attributes)!r}"
        )
    return {
        key: canonicalize_payload(attributes[key])
        for key in sorted(attributes.keys(), key=_string_key)
    }


def content_fingerprint(value: Any) -> str:
    """Stable SHA-256 hex digest over canonical JSON encoding."""
    canonical = canonicalize_payload(value)
    blob = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ─── Apex projection helpers ────────────────────────────────────────


def serialize_session(
    session: OperationalSession,
) -> dict[str, Any]:
    """Project an `OperationalSession` into a canonical dict."""
    return canonicalize_payload(
        {
            "session_id": str(session.identity.session_id),
            "scope": session.identity.scope.value,
            "tenant_id": session.identity.tenant_id,
            "principal_id": session.identity.principal_id,
            "external_handle": session.identity.external_handle,
            "opened_at": session.opened_at,
            "lifecycle": {
                "phase": session.lifecycle.phase.value,
                "recorded_at": session.lifecycle.recorded_at,
                "reason": session.lifecycle.reason,
            },
            "lineage": {
                "lineage_id": str(session.lineage.lineage_id),
                "root_session_id": str(
                    session.lineage.root_session_id
                ),
                "parent_session_id": (
                    str(session.lineage.parent_session_id)
                    if session.lineage.parent_session_id is not None
                    else None
                ),
                "ancestor_session_ids": [
                    str(a)
                    for a in session.lineage.ancestor_session_ids
                ],
                "depth": session.lineage.depth,
            },
            "context": (
                {
                    "environment": session.context.environment,
                    "labels": list(session.context.labels),
                    "attributes": dict(session.context.attributes),
                    "notes": session.context.notes,
                }
                if session.context is not None
                else None
            ),
            "sequence_head": session.sequence_head,
            "revision": session.revision,
        }
    )


def serialize_timeline_event(
    event: SessionTimelineEvent,
) -> dict[str, Any]:
    """Project a `SessionTimelineEvent` into a canonical dict."""
    return canonicalize_payload(
        {
            "event_id": str(event.event_id),
            "session_id": str(event.session_id),
            "sequence": event.sequence,
            "kind": event.kind.value,
            "continuity_mode": event.continuity_mode.value,
            "occurred_at": event.occurred_at,
            "recorded_at": event.recorded_at,
            "payload": dict(event.payload),
            "correlation_id": (
                str(event.correlation_id)
                if event.correlation_id is not None
                else None
            ),
            "annotation": event.annotation,
            "idempotency_key": event.idempotency_key,
        }
    )


def serialize_correlation(
    correlation: SessionCorrelation,
) -> dict[str, Any]:
    """Project a `SessionCorrelation` into a canonical dict."""
    return canonicalize_payload(
        {
            "correlation_id": str(correlation.correlation_id),
            "session_id": str(correlation.session_id),
            "kind": correlation.kind.value,
            "external_id": correlation.external_id,
            "external_correlation_id": (
                correlation.external_correlation_id
            ),
            "annotation": correlation.annotation,
            "recorded_at": correlation.recorded_at,
            "attributes": dict(correlation.attributes),
        }
    )


def _string_key(key: Any) -> str:
    return key if isinstance(key, str) else json.dumps(
        key, default=str, sort_keys=True
    )


__all__ = [
    "canonicalize_attributes",
    "canonicalize_payload",
    "content_fingerprint",
    "serialize_correlation",
    "serialize_session",
    "serialize_timeline_event",
]
