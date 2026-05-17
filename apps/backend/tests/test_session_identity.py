"""Session identity invariants — UUID4 + UUID5 discipline."""

from __future__ import annotations

import uuid

import pytest

from app.session.identity import (
    as_correlation_id,
    as_event_id,
    as_lineage_id,
    as_session_id,
    derive_correlation_id,
    derive_event_id,
    derive_lineage_id,
    derive_reconstruction_id,
    derive_session_id,
    derive_trace_id,
    generate_correlation_id,
    generate_event_id,
    generate_lineage_id,
    generate_reconstruction_id,
    generate_session_id,
    generate_trace_id,
)


def test_generators_emit_fresh_uuids() -> None:
    assert len({generate_session_id() for _ in range(50)}) == 50
    assert len({generate_event_id() for _ in range(50)}) == 50
    assert len({generate_lineage_id() for _ in range(50)}) == 50
    assert len({generate_correlation_id() for _ in range(50)}) == 50
    assert len({generate_trace_id() for _ in range(50)}) == 50
    assert len({generate_reconstruction_id() for _ in range(50)}) == 50


def test_derive_session_id_byte_stable() -> None:
    a = derive_session_id(
        scope="tenant",
        tenant_id="t1",
        principal_id="p1",
        external_handle="abc",
    )
    b = derive_session_id(
        scope="tenant",
        tenant_id="t1",
        principal_id="p1",
        external_handle="abc",
    )
    assert a == b


def test_derive_session_id_distinguishes_inputs() -> None:
    base = derive_session_id(
        scope="tenant",
        tenant_id="t1",
        principal_id="p1",
        external_handle="abc",
    )
    assert (
        derive_session_id(
            scope="tenant",
            tenant_id="t2",
            principal_id="p1",
            external_handle="abc",
        )
        != base
    )
    assert (
        derive_session_id(
            scope="principal",
            tenant_id="t1",
            principal_id="p1",
            external_handle="abc",
        )
        != base
    )
    assert (
        derive_session_id(
            scope="tenant",
            tenant_id="t1",
            principal_id="p1",
            external_handle="xyz",
        )
        != base
    )


def test_derive_session_id_rejects_empty_inputs() -> None:
    with pytest.raises(ValueError):
        derive_session_id(
            scope="",
            tenant_id="t",
            principal_id="p",
            external_handle="x",
        )
    with pytest.raises(ValueError):
        derive_session_id(
            scope="tenant",
            tenant_id="t",
            principal_id="p",
            external_handle="",
        )


def test_derive_event_id_byte_stable() -> None:
    sid = generate_session_id()
    a = derive_event_id(session_id=sid, sequence=3)
    b = derive_event_id(session_id=sid, sequence=3)
    assert a == b
    assert (
        derive_event_id(session_id=sid, sequence=4) != a
    )


def test_derive_event_id_rejects_negative_sequence() -> None:
    with pytest.raises(ValueError):
        derive_event_id(session_id=generate_session_id(), sequence=-1)


def test_derive_lineage_id_uses_root_session() -> None:
    sid = generate_session_id()
    assert derive_lineage_id(root_session_id=sid) == derive_lineage_id(
        root_session_id=sid
    )


def test_derive_correlation_id_byte_stable() -> None:
    sid = generate_session_id()
    a = derive_correlation_id(
        session_id=sid, kind="coordination", external_id="x"
    )
    b = derive_correlation_id(
        session_id=sid, kind="coordination", external_id="x"
    )
    assert a == b


def test_derive_correlation_id_distinguishes_kind() -> None:
    sid = generate_session_id()
    assert (
        derive_correlation_id(
            session_id=sid, kind="coordination", external_id="x"
        )
        != derive_correlation_id(
            session_id=sid, kind="governance", external_id="x"
        )
    )


def test_namespaces_isolate_seeds() -> None:
    """Different derivers with the same seed produce different uuids."""
    seed = "shared"
    assert (
        derive_trace_id(seed=seed)
        != derive_reconstruction_id(seed=seed)
    )


def test_as_helpers_round_trip() -> None:
    u = uuid.uuid4()
    assert as_session_id(str(u)) == u
    assert as_event_id(str(u)) == u
    assert as_lineage_id(str(u)) == u
    assert as_correlation_id(str(u)) == u
    assert as_session_id(u) == u
