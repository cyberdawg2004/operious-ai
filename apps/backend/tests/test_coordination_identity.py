"""Coordination identity primitives — replay-safety + lineage continuity.

Properties pinned:

* `generate_*` returns distinct UUIDs across calls (live path).
* `derive_*` is byte-stable for fixed seeds (replay path).
* `derive_*` requires a non-empty seed (refuses to silently swallow
  empty inputs that would seed everything onto the namespace UUID).
* The three namespaces are distinct — same seed under different
  derivers produces different UUIDs (no cross-substrate collision).
* `as_*` coerces from both `uuid.UUID` and string inputs.
"""

from __future__ import annotations

import uuid

import pytest

from app.coordination.identity import (
    as_coordination_id,
    as_correlation_id,
    as_message_id,
    derive_coordination_id,
    derive_correlation_id,
    derive_message_id,
    generate_coordination_id,
    generate_correlation_id,
    generate_message_id,
)


# ─── Generators ──────────────────────────────────────────────────────


def test_generate_coordination_id_unique() -> None:
    ids = {generate_coordination_id() for _ in range(100)}
    assert len(ids) == 100


def test_generate_message_id_unique() -> None:
    ids = {generate_message_id() for _ in range(100)}
    assert len(ids) == 100


def test_generate_correlation_id_unique() -> None:
    ids = {generate_correlation_id() for _ in range(100)}
    assert len(ids) == 100


def test_generate_returns_uuid_instances() -> None:
    assert isinstance(generate_coordination_id(), uuid.UUID)
    assert isinstance(generate_message_id(), uuid.UUID)
    assert isinstance(generate_correlation_id(), uuid.UUID)


# ─── Derivers — byte-stable replay path ──────────────────────────────


def test_derive_coordination_id_is_byte_stable() -> None:
    a = derive_coordination_id(seed="pipeline:1:dispatch:1")
    b = derive_coordination_id(seed="pipeline:1:dispatch:1")
    assert a == b


def test_derive_message_id_is_byte_stable() -> None:
    a = derive_message_id(seed="msg:agent:retriever:1")
    b = derive_message_id(seed="msg:agent:retriever:1")
    assert a == b


def test_derive_correlation_id_is_byte_stable() -> None:
    a = derive_correlation_id(seed="op:tenant:acme:operation:7")
    b = derive_correlation_id(seed="op:tenant:acme:operation:7")
    assert a == b


def test_derive_different_seeds_different_ids() -> None:
    assert derive_coordination_id(seed="a") != derive_coordination_id(seed="b")
    assert derive_message_id(seed="a") != derive_message_id(seed="b")
    assert derive_correlation_id(seed="a") != derive_correlation_id(seed="b")


def test_derive_rejects_empty_seed() -> None:
    with pytest.raises(ValueError):
        derive_coordination_id(seed="")
    with pytest.raises(ValueError):
        derive_message_id(seed="")
    with pytest.raises(ValueError):
        derive_correlation_id(seed="")


def test_namespaces_are_distinct() -> None:
    seed = "common:seed"
    coord = derive_coordination_id(seed=seed)
    msg = derive_message_id(seed=seed)
    corr = derive_correlation_id(seed=seed)
    assert coord != msg
    assert coord != corr
    assert msg != corr


# ─── Coercers ─────────────────────────────────────────────────────────


def test_as_coordination_id_accepts_uuid_and_string() -> None:
    raw = uuid.uuid4()
    assert as_coordination_id(raw) == raw
    assert as_coordination_id(str(raw)) == raw


def test_as_message_id_accepts_uuid_and_string() -> None:
    raw = uuid.uuid4()
    assert as_message_id(raw) == raw
    assert as_message_id(str(raw)) == raw


def test_as_correlation_id_accepts_uuid_and_string() -> None:
    raw = uuid.uuid4()
    assert as_correlation_id(raw) == raw
    assert as_correlation_id(str(raw)) == raw


def test_as_coercion_rejects_malformed_string() -> None:
    with pytest.raises(ValueError):
        as_coordination_id("not-a-uuid")
