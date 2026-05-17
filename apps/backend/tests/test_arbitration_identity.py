"""Arbitration identity invariants.

* `generate_*` returns fresh UUID4s per call.
* `derive_*` is byte-stable for the same seed.
* Different namespaces never collide.
* `as_*` coerces strings.
* `derive_finding_id` is stable across replays.
"""

from __future__ import annotations

import uuid

import pytest

from app.arbitration.identity import (
    as_case_id,
    as_chain_id,
    as_conflict_id,
    as_evaluation_id,
    as_recommendation_id,
    as_signal_id,
    derive_case_id,
    derive_chain_id,
    derive_conflict_id,
    derive_deadlock_witness_id,
    derive_evaluation_id,
    derive_finding_id,
    derive_recommendation_id,
    derive_signal_id,
    generate_case_id,
    generate_conflict_id,
    generate_evaluation_id,
    generate_recommendation_id,
    generate_signal_id,
)


# ─── generate_* freshness ────────────────────────────────────────────


def test_generators_emit_fresh_uuids() -> None:
    ids = {generate_case_id() for _ in range(50)}
    assert len(ids) == 50
    ids = {generate_evaluation_id() for _ in range(50)}
    assert len(ids) == 50
    ids = {generate_signal_id() for _ in range(50)}
    assert len(ids) == 50
    ids = {generate_conflict_id() for _ in range(50)}
    assert len(ids) == 50
    ids = {generate_recommendation_id() for _ in range(50)}
    assert len(ids) == 50


# ─── derive_* determinism ────────────────────────────────────────────


def test_derive_is_byte_stable_for_same_seed() -> None:
    assert derive_case_id(seed="alpha") == derive_case_id(seed="alpha")
    assert derive_evaluation_id(seed="alpha") == derive_evaluation_id(
        seed="alpha"
    )
    assert derive_signal_id(seed="alpha") == derive_signal_id(
        seed="alpha"
    )
    assert derive_conflict_id(seed="alpha") == derive_conflict_id(
        seed="alpha"
    )
    assert derive_recommendation_id(
        seed="alpha"
    ) == derive_recommendation_id(seed="alpha")
    assert derive_chain_id(
        evaluator_names=("b", "a")
    ) == derive_chain_id(evaluator_names=("a", "b"))


def test_derive_namespaces_are_independent() -> None:
    seed = "shared"
    case = derive_case_id(seed=seed)
    eval_id = derive_evaluation_id(seed=seed)
    sig = derive_signal_id(seed=seed)
    conf = derive_conflict_id(seed=seed)
    rec = derive_recommendation_id(seed=seed)
    assert (
        len({case, eval_id, sig, conf, rec}) == 5
    ), "different namespaces must not collide for shared seed"


def test_derive_empty_seed_rejected() -> None:
    with pytest.raises(ValueError):
        derive_case_id(seed="")
    with pytest.raises(ValueError):
        derive_evaluation_id(seed="")
    with pytest.raises(ValueError):
        derive_signal_id(seed="")
    with pytest.raises(ValueError):
        derive_conflict_id(seed="")
    with pytest.raises(ValueError):
        derive_recommendation_id(seed="")
    with pytest.raises(ValueError):
        derive_chain_id(evaluator_names=())


# ─── finding / deadlock-witness id derivation ────────────────────────


def test_finding_id_stable_across_replays() -> None:
    evaluation_id = derive_evaluation_id(seed="case-1")
    f1 = derive_finding_id(
        evaluation_id=evaluation_id,
        evaluator_name="evaluator_a",
        code="arbitration.no_conflict",
        ordinal=0,
    )
    f2 = derive_finding_id(
        evaluation_id=evaluation_id,
        evaluator_name="evaluator_a",
        code="arbitration.no_conflict",
        ordinal=0,
    )
    assert f1 == f2


def test_finding_id_changes_with_ordinal() -> None:
    evaluation_id = derive_evaluation_id(seed="case-1")
    f0 = derive_finding_id(
        evaluation_id=evaluation_id,
        evaluator_name="evaluator_a",
        code="x",
        ordinal=0,
    )
    f1 = derive_finding_id(
        evaluation_id=evaluation_id,
        evaluator_name="evaluator_a",
        code="x",
        ordinal=1,
    )
    assert f0 != f1


def test_deadlock_witness_id_stable_across_replays() -> None:
    evaluation_id = derive_evaluation_id(seed="case-1")
    w1 = derive_deadlock_witness_id(
        evaluation_id=evaluation_id,
        kind="iteration_exhausted",
        ordinal=0,
    )
    w2 = derive_deadlock_witness_id(
        evaluation_id=evaluation_id,
        kind="iteration_exhausted",
        ordinal=0,
    )
    assert w1 == w2


# ─── as_* coercion ──────────────────────────────────────────────────


def test_as_coerces_strings_to_typed_ids() -> None:
    u = uuid.uuid4()
    s = str(u)
    assert as_case_id(s) == u
    assert as_evaluation_id(s) == u
    assert as_chain_id(s) == u
    assert as_signal_id(s) == u
    assert as_conflict_id(s) == u
    assert as_recommendation_id(s) == u


def test_as_passthrough_for_uuids() -> None:
    u = uuid.uuid4()
    assert as_case_id(u) == u
    assert as_evaluation_id(u) == u
