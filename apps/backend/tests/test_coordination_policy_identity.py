"""Coordination-policy identity primitives — replay safety."""

from __future__ import annotations

import uuid

import pytest

from app.coordination.policy.identity import (
    CoordinationPolicyChainId,
    CoordinationPolicyEvaluationId,
    CoordinationPolicyId,
    as_chain_id,
    as_evaluation_id,
    as_policy_id,
    derive_chain_id,
    derive_evaluation_id,
    derive_finding_id,
    derive_policy_id,
    generate_evaluation_id,
    generate_policy_id,
)


# ─── UUID4 generators are unique per call ─────────────────────────────


def test_generate_policy_id_is_unique() -> None:
    a = generate_policy_id()
    b = generate_policy_id()
    assert a != b
    assert isinstance(a, uuid.UUID)


def test_generate_evaluation_id_is_unique() -> None:
    a = generate_evaluation_id()
    b = generate_evaluation_id()
    assert a != b


# ─── UUID5 derivers are byte-stable for fixed seeds ───────────────────


def test_derive_policy_id_is_stable_for_same_seed() -> None:
    a = derive_policy_id(seed="policy.alpha")
    b = derive_policy_id(seed="policy.alpha")
    assert a == b


def test_derive_evaluation_id_is_stable_for_same_seed() -> None:
    a = derive_evaluation_id(seed="op:42")
    b = derive_evaluation_id(seed="op:42")
    assert a == b


def test_derive_chain_id_is_order_insensitive() -> None:
    a = derive_chain_id(evaluator_names=("a", "b", "c"))
    b = derive_chain_id(evaluator_names=("c", "a", "b"))
    assert a == b


def test_derive_chain_id_is_sensitive_to_membership() -> None:
    assert derive_chain_id(
        evaluator_names=("a", "b")
    ) != derive_chain_id(evaluator_names=("a", "b", "c"))


def test_derive_finding_id_is_stable() -> None:
    eval_id = derive_evaluation_id(seed="op:42")
    a = derive_finding_id(
        evaluation_id=eval_id,
        evaluator_name="topology",
        code="topology.denied",
        ordinal=0,
    )
    b = derive_finding_id(
        evaluation_id=eval_id,
        evaluator_name="topology",
        code="topology.denied",
        ordinal=0,
    )
    assert a == b


def test_derive_finding_id_varies_with_ordinal() -> None:
    eval_id = derive_evaluation_id(seed="op:42")
    a = derive_finding_id(
        evaluation_id=eval_id,
        evaluator_name="topology",
        code="topology.denied",
        ordinal=0,
    )
    b = derive_finding_id(
        evaluation_id=eval_id,
        evaluator_name="topology",
        code="topology.denied",
        ordinal=1,
    )
    assert a != b


# ─── Namespaces are distinct ──────────────────────────────────────────


def test_namespaces_are_distinct() -> None:
    seed = "ns-collision-canary"
    p = derive_policy_id(seed=seed)
    e = derive_evaluation_id(seed=seed)
    assert p != e


# ─── Coercers ─────────────────────────────────────────────────────────


def test_as_policy_id_accepts_uuid_and_str() -> None:
    u = uuid.uuid4()
    assert as_policy_id(u) == u
    assert as_policy_id(str(u)) == u


def test_as_evaluation_id_accepts_uuid_and_str() -> None:
    u = uuid.uuid4()
    assert as_evaluation_id(u) == u
    assert as_evaluation_id(str(u)) == u


def test_as_chain_id_accepts_uuid_and_str() -> None:
    u = uuid.uuid4()
    assert as_chain_id(u) == u
    assert as_chain_id(str(u)) == u


# ─── Empty-seed guard ─────────────────────────────────────────────────


def test_derive_policy_id_requires_nonempty_seed() -> None:
    with pytest.raises(ValueError):
        derive_policy_id(seed="")


def test_derive_evaluation_id_requires_nonempty_seed() -> None:
    with pytest.raises(ValueError):
        derive_evaluation_id(seed="")


def test_derive_chain_id_requires_at_least_one_name() -> None:
    with pytest.raises(ValueError):
        derive_chain_id(evaluator_names=())


# Silence unused-import warnings for the typed aliases.
_ = (
    CoordinationPolicyId,
    CoordinationPolicyEvaluationId,
    CoordinationPolicyChainId,
)
