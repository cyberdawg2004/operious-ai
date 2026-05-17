"""Boundary identity invariants.

Critical invariant: derived event ids are byte-stable for the same
external coordinates — that's the foundation of replay-safe
ingestion.
"""

from __future__ import annotations

import uuid

import pytest

from app.boundary.identity import (
    as_egress_id,
    as_event_id,
    as_external_conversation_id,
    as_external_message_id,
    as_ingress_id,
    derive_egress_id,
    derive_event_id,
    derive_ingress_id,
    derive_replay_key,
    derive_trace_id,
    generate_egress_id,
    generate_event_id,
    generate_ingress_id,
)


# ─── generate_* freshness ────────────────────────────────────────────


def test_generators_emit_fresh_uuids() -> None:
    assert len({generate_event_id() for _ in range(50)}) == 50
    assert len({generate_ingress_id() for _ in range(50)}) == 50
    assert len({generate_egress_id() for _ in range(50)}) == 50


# ─── derive_event_id determinism ────────────────────────────────────


def test_derive_event_id_byte_stable() -> None:
    a = derive_event_id(
        source_type="zendesk",
        external_message_id="evt-1",
        tenant_id="tenant-1",
    )
    b = derive_event_id(
        source_type="zendesk",
        external_message_id="evt-1",
        tenant_id="tenant-1",
    )
    assert a == b


def test_derive_event_id_distinguishes_tenants() -> None:
    a = derive_event_id(
        source_type="zendesk",
        external_message_id="evt-1",
        tenant_id="tenant-A",
    )
    b = derive_event_id(
        source_type="zendesk",
        external_message_id="evt-1",
        tenant_id="tenant-B",
    )
    assert a != b


def test_derive_event_id_distinguishes_sources() -> None:
    a = derive_event_id(
        source_type="zendesk",
        external_message_id="X",
    )
    b = derive_event_id(
        source_type="whatsapp",
        external_message_id="X",
    )
    assert a != b


def test_derive_event_id_rejects_empty_inputs() -> None:
    with pytest.raises(ValueError):
        derive_event_id(
            source_type="", external_message_id="x"
        )
    with pytest.raises(ValueError):
        derive_event_id(
            source_type="zendesk", external_message_id=""
        )


# ─── derive_replay_key determinism + namespace separation ────────────


def test_derive_replay_key_is_byte_stable() -> None:
    a = derive_replay_key(
        source_type="zendesk", external_message_id="evt-1"
    )
    b = derive_replay_key(
        source_type="zendesk", external_message_id="evt-1"
    )
    assert a == b


def test_replay_key_is_distinct_from_event_id() -> None:
    """Different namespaces ⇒ different uuids for same coordinates."""
    coords = {
        "source_type": "zendesk",
        "external_message_id": "evt-1",
        "tenant_id": "t1",
    }
    assert derive_event_id(**coords) != derive_replay_key(**coords)


# ─── derive_ingress_id / derive_egress_id / derive_trace_id ──────────


def test_derive_ingress_id_byte_stable() -> None:
    a = derive_ingress_id(seed="abc")
    b = derive_ingress_id(seed="abc")
    assert a == b


def test_derive_egress_id_byte_stable() -> None:
    a = derive_egress_id(seed="abc")
    b = derive_egress_id(seed="abc")
    assert a == b


def test_derive_trace_id_byte_stable() -> None:
    a = derive_trace_id(seed="abc")
    b = derive_trace_id(seed="abc")
    assert a == b


def test_namespaces_isolate_seeds() -> None:
    seed = "shared"
    ingress = derive_ingress_id(seed=seed)
    egress = derive_egress_id(seed=seed)
    trace = derive_trace_id(seed=seed)
    assert len({ingress, egress, trace}) == 3


def test_derive_helpers_reject_empty_seed() -> None:
    with pytest.raises(ValueError):
        derive_ingress_id(seed="")
    with pytest.raises(ValueError):
        derive_egress_id(seed="")
    with pytest.raises(ValueError):
        derive_trace_id(seed="")


# ─── as_* coercion ──────────────────────────────────────────────────


def test_as_uuid_helpers_round_trip() -> None:
    u = uuid.uuid4()
    assert as_event_id(str(u)) == u
    assert as_ingress_id(str(u)) == u
    assert as_egress_id(str(u)) == u
    assert as_event_id(u) == u


def test_as_external_message_id_rejects_empty() -> None:
    with pytest.raises(ValueError):
        as_external_message_id("")
    assert as_external_message_id("evt-1") == "evt-1"


def test_as_external_conversation_id_rejects_empty() -> None:
    with pytest.raises(ValueError):
        as_external_conversation_id("")
    assert (
        as_external_conversation_id("conv-1") == "conv-1"
    )
