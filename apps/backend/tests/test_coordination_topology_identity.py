"""Coordination-topology identity primitives.

Pinned properties:

* every namespace is unique,
* `generate_*` produces fresh UUID4s,
* `derive_*` is byte-stable for identical seeds and namespace-
  separated across primitive types,
* coercion helpers (`as_*`) accept both `uuid.UUID` and `str`.
"""

from __future__ import annotations

import uuid

import pytest

from app.coordination.topology.identity import (
    as_chain_id,
    as_edge_id,
    as_evaluation_id,
    as_node_id,
    as_topology_id,
    derive_chain_id,
    derive_edge_id,
    derive_evaluation_id,
    derive_finding_id,
    derive_node_id,
    derive_topology_id,
    generate_edge_id,
    generate_evaluation_id,
    generate_node_id,
    generate_topology_id,
)


def test_generate_returns_unique_uuids() -> None:
    assert generate_topology_id() != generate_topology_id()
    assert generate_evaluation_id() != generate_evaluation_id()
    assert generate_node_id() != generate_node_id()
    assert generate_edge_id() != generate_edge_id()


def test_derive_is_byte_stable() -> None:
    assert derive_topology_id(seed="t1") == derive_topology_id(seed="t1")
    assert derive_evaluation_id(seed="e1") == derive_evaluation_id(seed="e1")
    assert derive_node_id(seed="n1") == derive_node_id(seed="n1")
    assert derive_edge_id(seed="e1") == derive_edge_id(seed="e1")


def test_derive_namespaces_are_distinct() -> None:
    seed = "operious"
    ids = {
        derive_topology_id(seed=seed),
        derive_evaluation_id(seed=seed),
        derive_node_id(seed=seed),
        derive_edge_id(seed=seed),
    }
    assert len(ids) == 4


def test_derive_chain_id_is_order_independent() -> None:
    a = derive_chain_id(evaluator_names=("a", "b", "c"))
    b = derive_chain_id(evaluator_names=("c", "a", "b"))
    assert a == b


def test_derive_chain_id_requires_at_least_one_evaluator() -> None:
    with pytest.raises(ValueError):
        derive_chain_id(evaluator_names=())


def test_derive_finding_id_is_byte_stable() -> None:
    eval_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    a = derive_finding_id(
        evaluation_id=eval_id,
        evaluator_name="allowed_path",
        code="path.denied",
        ordinal=0,
    )
    b = derive_finding_id(
        evaluation_id=eval_id,
        evaluator_name="allowed_path",
        code="path.denied",
        ordinal=0,
    )
    c = derive_finding_id(
        evaluation_id=eval_id,
        evaluator_name="allowed_path",
        code="path.denied",
        ordinal=1,
    )
    assert a == b
    assert a != c


def test_coercion_helpers_accept_uuid_and_str() -> None:
    src = uuid.uuid4()
    assert as_topology_id(src) == src
    assert as_topology_id(str(src)) == src
    assert as_evaluation_id(src) == src
    assert as_chain_id(src) == src
    assert as_node_id(src) == src
    assert as_edge_id(src) == src
