"""Boundary substrate enum vocabulary — pinned wire-format values.

Five typed vocabularies the boundary substrate speaks in. All
`StrEnum` so JSON round-trips are transparent and the persistence
layer can store the string value verbatim.

Wire-format discipline: every value below is pinned. Renaming a
value is a breaking change to every previously persisted boundary
record. `tests/test_boundary_invariants.py` pins the catalogue so
accidental drift fails at import time.

Critical architectural rule (Sprint M):

* The boundary is a **translation substrate**, not an
  orchestration substrate. The vocabularies below describe WHAT
  the substrate observed about an external event; they never
  instruct WHAT to do next.
* External vocabularies (Zendesk/WhatsApp/Twilio/…) are mapped
  INTO this canonical substrate vocabulary at the adapter
  boundary; the substrate never re-exports raw external strings.
"""

from __future__ import annotations

from enum import StrEnum


class BoundaryDirection(StrEnum):
    """Direction of a boundary translation.

    INGRESS — external system → Operious internal artifact.
    EGRESS  — Operious internal artifact → external mutation request.
    """

    INGRESS = "ingress"
    EGRESS = "egress"


class BoundarySourceType(StrEnum):
    """Canonical external-source classification.

    Closed vocabulary. Adding a value is a deliberate vocabulary
    change — adapters MUST classify themselves against this set.

    The names are deliberately lowercase so they round-trip
    identically in nested JSON alongside other substrate enums.
    """

    ZENDESK = "zendesk"
    WHATSAPP = "whatsapp"
    TWILIO_VOICE = "twilio_voice"
    TWILIO_SMS = "twilio_sms"
    EMAIL = "email"
    SLACK = "slack"
    REST_API = "rest_api"
    GENERIC = "generic"


class BoundaryMessageType(StrEnum):
    """Canonical message-type classification across sources.

    Adapters translate source-specific message kinds INTO this
    closed vocabulary. The substrate refuses to forward raw
    external strings.

    MESSAGE_RECEIVED   — an inbound message in a conversation.
    MESSAGE_DELIVERED  — an outbound message acknowledged delivered.
    STATUS_UPDATE      — a state transition observation
                          (e.g. ticket-status, call-status).
    EVENT_CREATED      — a new external entity appeared.
    EVENT_UPDATED      — an existing external entity changed.
    STREAM_FRAME       — a chunk of a streaming session
                          (e.g. Twilio media frame).
    PRESENCE_UPDATE    — typing / online / read receipts.
    UNKNOWN            — sentinel; adapter could not classify.
    """

    MESSAGE_RECEIVED = "message_received"
    MESSAGE_DELIVERED = "message_delivered"
    STATUS_UPDATE = "status_update"
    EVENT_CREATED = "event_created"
    EVENT_UPDATED = "event_updated"
    STREAM_FRAME = "stream_frame"
    PRESENCE_UPDATE = "presence_update"
    UNKNOWN = "unknown"


class BoundaryNormalizationStatus(StrEnum):
    """Outcome of running an adapter's normalisation pass.

    OK                 — payload normalised successfully.
    MALFORMED          — payload does not conform to the adapter's
                          declared shape.
    UNAUTHENTICATED    — signature / token check failed.
    UNSUPPORTED_TYPE   — payload classified as a kind the adapter
                          does not handle.
    ADAPTER_ERROR      — adapter raised internally; the substrate
                          captured the failure rather than letting
                          it propagate.
    """

    OK = "ok"
    MALFORMED = "malformed"
    UNAUTHENTICATED = "unauthenticated"
    UNSUPPORTED_TYPE = "unsupported_type"
    ADAPTER_ERROR = "adapter_error"


class BoundaryReplayDisposition(StrEnum):
    """Replay-detection classification.

    NEW                — first time the substrate sees this
                          deterministic replay key.
    REPLAY_OF_KNOWN    — duplicate delivery; deterministic key
                          matches an existing event AND the
                          normalised content is byte-identical.
    LINEAGE_DRIFT      — deterministic key matches an existing
                          event but the normalised content differs.
                          The substrate refuses to silently
                          rewrite lineage; it surfaces the drift.
    INVALID_KEY        — replay key derivation failed (missing
                          external_message_id, malformed source).
    """

    NEW = "new"
    REPLAY_OF_KNOWN = "replay_of_known"
    LINEAGE_DRIFT = "lineage_drift"
    INVALID_KEY = "invalid_key"


__all__ = [
    "BoundaryDirection",
    "BoundarySourceType",
    "BoundaryMessageType",
    "BoundaryNormalizationStatus",
    "BoundaryReplayDisposition",
]
