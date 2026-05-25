"""Boundary identity primitives.

Five typed identifiers, mirroring the discipline of every sibling
substrate:

* `BoundaryEventId`           — stable id of an external event,
                                 deterministically derived from
                                 ``(source_type, external_message_id)``
                                 so duplicate webhook deliveries
                                 resolve to the SAME id.
* `BoundaryIngressId`         — one per ingest() call.
* `BoundaryEgressId`          — one per emit() call.
* `ExternalMessageId`         — typed wrapper around the external
                                 system's message identifier
                                 (e.g. Zendesk event id).
* `ExternalConversationId`    — typed wrapper around the external
                                 system's conversation identifier
                                 (e.g. WhatsApp wa_id, Twilio CallSid).

Generators / derivers
─────────────────────

* `generate_*` — UUID4 runtime path.
* `derive_*`   — UUID5 over a pinned namespace + seed. Same seed →
                  same UUID bit-for-bit. The replay detector
                  derives `BoundaryEventId` deterministically from
                  ``(source_type, external_message_id)``.

The namespaces are permanent constants. Changing one is a breaking
change to every previously derived identifier in the substrate.
"""

from __future__ import annotations

import itertools
import secrets
import uuid
from typing import NewType

from app.identity import project_optional_str


# ─── Type aliases ────────────────────────────────────────────────────


BoundaryEventId = NewType("BoundaryEventId", uuid.UUID)
BoundaryIngressId = NewType("BoundaryIngressId", uuid.UUID)
BoundaryEgressId = NewType("BoundaryEgressId", uuid.UUID)
ExternalMessageId = NewType("ExternalMessageId", str)
ExternalConversationId = NewType("ExternalConversationId", str)


# ─── Namespaces — permanent constants ────────────────────────────────


_EVENT_NAMESPACE: uuid.UUID = uuid.UUID(
    "b0c1d2e3-0001-4001-8001-000000000001"
)
_INGRESS_NAMESPACE: uuid.UUID = uuid.UUID(
    "b0c1d2e3-0002-4002-8002-000000000002"
)
_EGRESS_NAMESPACE: uuid.UUID = uuid.UUID(
    "b0c1d2e3-0003-4003-8003-000000000003"
)
_REPLAY_KEY_NAMESPACE: uuid.UUID = uuid.UUID(
    "b0c1d2e3-0004-4004-8004-000000000004"
)
_TRACE_NAMESPACE: uuid.UUID = uuid.UUID(
    "b0c1d2e3-0005-4005-8005-000000000005"
)
_BATCH_BOUNDARY_NAMESPACE: uuid.UUID = uuid.UUID(
    "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
)
_RUNTIME_BOOT_ID = secrets.token_urlsafe(32)
_RUNTIME_COUNTER = itertools.count()


# ─── Runtime path: fresh UUID4 per call ──────────────────────────────


def generate_event_id() -> BoundaryEventId:
    """Random event id; only used when external_message_id is absent."""
    return BoundaryEventId(uuid.uuid5(_EVENT_NAMESPACE, _runtime_seed("event")))


def generate_ingress_id() -> BoundaryIngressId:
    return BoundaryIngressId(uuid.uuid5(_INGRESS_NAMESPACE, _runtime_seed("ingress")))


def generate_egress_id() -> BoundaryEgressId:
    return BoundaryEgressId(uuid.uuid5(_EGRESS_NAMESPACE, _runtime_seed("egress")))


def _runtime_seed(label: str) -> str:
    return f"runtime|{label}|{_RUNTIME_BOOT_ID}|{next(_RUNTIME_COUNTER)}"


# ─── Replay path: deterministic UUID5 from a stable seed ─────────────


def derive_event_id(
    *,
    source_type: str,
    external_message_id: str,
    tenant_id: str | None = None,
) -> BoundaryEventId:
    """Derive a deterministic event id from external coordinates.

    Two webhook deliveries that share
    ``(source_type, external_message_id, tenant_id)`` produce
    BYTE-IDENTICAL `BoundaryEventId`s. The optional `tenant_id`
    namespaces multi-tenant deployments so external systems that
    re-use ids across tenants don't collide.
    """
    if not source_type:
        raise ValueError(
            "derive_event_id requires a non-empty source_type"
        )
    if not external_message_id:
        raise ValueError(
            "derive_event_id requires a non-empty "
            "external_message_id"
        )
    # ``project_optional_str`` disambiguates ``tenant_id=None`` from
    # ``tenant_id=""`` in the seed (Wedge B4 closure of audit CO-1).
    seed = (
        f"{source_type}|"
        f"{project_optional_str(tenant_id)}|"
        f"{external_message_id}"
    )
    return BoundaryEventId(uuid.uuid5(_EVENT_NAMESPACE, seed))


def derive_ingress_id(*, seed: str) -> BoundaryIngressId:
    if not seed:
        raise ValueError(
            "derive_ingress_id requires a non-empty seed"
        )
    return BoundaryIngressId(uuid.uuid5(_INGRESS_NAMESPACE, seed))


def make_boundary_id(
    tenant_id: str,
    channel_type: str,
    source_id: str,
    external_message_id: str,
) -> str:
    """Derive the deterministic batch-ingest boundary id."""
    if not tenant_id:
        raise ValueError("make_boundary_id requires a non-empty tenant_id")
    if not channel_type:
        raise ValueError(
            "make_boundary_id requires a non-empty channel_type"
        )
    if not source_id:
        raise ValueError("make_boundary_id requires a non-empty source_id")
    if not external_message_id:
        raise ValueError(
            "make_boundary_id requires a non-empty external_message_id"
        )
    seed = (
        f"boundary:{tenant_id}:{channel_type}:"
        f"{source_id}:{external_message_id}"
    )
    return str(uuid.uuid5(_BATCH_BOUNDARY_NAMESPACE, seed))


def derive_egress_id(*, seed: str) -> BoundaryEgressId:
    if not seed:
        raise ValueError(
            "derive_egress_id requires a non-empty seed"
        )
    return BoundaryEgressId(uuid.uuid5(_EGRESS_NAMESPACE, seed))


def derive_replay_key(
    *,
    source_type: str,
    external_message_id: str,
    tenant_id: str | None = None,
) -> uuid.UUID:
    """Derive the deterministic replay key for the idempotency registry.

    Distinct from ``derive_event_id`` (different namespace) so the
    two derived ids never collide even when seeded from the same
    coordinates. The replay key is the registry's primary index.
    """
    if not source_type or not external_message_id:
        raise ValueError(
            "derive_replay_key requires non-empty source_type and "
            "external_message_id"
        )
    # ``project_optional_str`` disambiguates ``tenant_id=None`` from
    # ``tenant_id=""`` in the seed (Wedge B4 closure of audit CO-1).
    seed = (
        f"{source_type}|"
        f"{project_optional_str(tenant_id)}|"
        f"{external_message_id}"
    )
    return uuid.uuid5(_REPLAY_KEY_NAMESPACE, seed)


def derive_trace_id(*, seed: str) -> uuid.UUID:
    """Derive a deterministic trace identifier."""
    if not seed:
        raise ValueError("derive_trace_id requires a non-empty seed")
    return uuid.uuid5(_TRACE_NAMESPACE, seed)


# ─── Boundary coercion helpers ───────────────────────────────────────


def as_event_id(value: uuid.UUID | str) -> BoundaryEventId:
    return BoundaryEventId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_ingress_id(value: uuid.UUID | str) -> BoundaryIngressId:
    return BoundaryIngressId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_egress_id(value: uuid.UUID | str) -> BoundaryEgressId:
    return BoundaryEgressId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_external_message_id(value: str) -> ExternalMessageId:
    if not value:
        raise ValueError(
            "external_message_id must be a non-empty string"
        )
    return ExternalMessageId(value)


def as_external_conversation_id(
    value: str,
) -> ExternalConversationId:
    if not value:
        raise ValueError(
            "external_conversation_id must be a non-empty string"
        )
    return ExternalConversationId(value)


__all__ = [
    "BoundaryEventId",
    "BoundaryIngressId",
    "BoundaryEgressId",
    "ExternalMessageId",
    "ExternalConversationId",
    "generate_event_id",
    "generate_ingress_id",
    "generate_egress_id",
    "derive_event_id",
    "derive_ingress_id",
    "derive_egress_id",
    "make_boundary_id",
    "derive_replay_key",
    "derive_trace_id",
    "as_event_id",
    "as_ingress_id",
    "as_egress_id",
    "as_external_message_id",
    "as_external_conversation_id",
]
