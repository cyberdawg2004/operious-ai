"""Sprint I Hardening — identity layer tests.

Properties pinned:

* `generate_*_id` produces UUID4 values, unique across calls,
* `derive_*_id(seed=...)` is deterministic — same seed → same UUID,
* empty seed raises (no silent collisions),
* `CorrelationContext` + `CorrelationKey` are frozen + hashable,
* `decision_id` and `trace_id` come from different namespaces
  (so seeded derivation produces distinct UUIDs even for the same
  seed).
"""

from __future__ import annotations

import uuid

import pytest

from app.governance.identity import (
    DECISION_NAMESPACE,
    TRACE_NAMESPACE,
    CorrelationContext,
    CorrelationKey,
    derive_decision_id,
    derive_trace_id,
    generate_decision_id,
    generate_trace_id,
)


# ─── generate_* uniqueness ────────────────────────────────────────────


def test_generate_decision_id_is_unique_across_calls() -> None:
    ids = {generate_decision_id() for _ in range(50)}
    assert len(ids) == 50


def test_generate_trace_id_is_unique_across_calls() -> None:
    ids = {generate_trace_id() for _ in range(50)}
    assert len(ids) == 50


def test_generate_decision_id_returns_uuid4() -> None:
    uid = generate_decision_id()
    assert uid.version == 4


def test_generate_trace_id_returns_uuid4() -> None:
    uid = generate_trace_id()
    assert uid.version == 4


# ─── derive_* determinism ─────────────────────────────────────────────


def test_derive_decision_id_is_deterministic_for_fixed_seed() -> None:
    a = derive_decision_id(seed="rag.assemble_context/req-1/pre_retrieval")
    b = derive_decision_id(seed="rag.assemble_context/req-1/pre_retrieval")
    assert a == b


def test_derive_trace_id_is_deterministic_for_fixed_seed() -> None:
    a = derive_trace_id(seed="rag.assemble_context/req-1")
    b = derive_trace_id(seed="rag.assemble_context/req-1")
    assert a == b


def test_derive_decision_id_differs_per_seed() -> None:
    a = derive_decision_id(seed="seed-1")
    b = derive_decision_id(seed="seed-2")
    assert a != b


def test_derive_decision_id_and_trace_id_use_different_namespaces() -> None:
    """Same seed across namespaces must NOT collide."""
    d = derive_decision_id(seed="same-seed")
    t = derive_trace_id(seed="same-seed")
    assert d != t
    # Both produced via uuid5; both are version 5.
    assert d.version == 5
    assert t.version == 5


def test_derive_decision_id_rejects_empty_seed() -> None:
    with pytest.raises(ValueError):
        derive_decision_id(seed="")


def test_derive_trace_id_rejects_empty_seed() -> None:
    with pytest.raises(ValueError):
        derive_trace_id(seed="")


def test_namespaces_are_distinct_and_pinned() -> None:
    assert DECISION_NAMESPACE != TRACE_NAMESPACE
    # Pinned constants; changing them would invalidate every previously
    # derived UUID. The test exists to catch accidental edits.
    assert DECISION_NAMESPACE == uuid.UUID("4d2c10a2-6c00-4f7c-8b3a-1f8d0c7e0001")
    assert TRACE_NAMESPACE == uuid.UUID("4d2c10a2-6c00-4f7c-8b3a-1f8d0c7e0002")


# ─── CorrelationContext / CorrelationKey ──────────────────────────────


def test_correlation_context_is_frozen_and_hashable() -> None:
    cid = uuid.uuid4()
    a = CorrelationContext(correlation_id=cid, request_id="r1")
    b = CorrelationContext(correlation_id=cid, request_id="r1")
    assert a == b
    assert hash(a) == hash(b)
    with pytest.raises((AttributeError, Exception)):
        a.request_id = "r2"  # type: ignore[misc]


def test_correlation_key_carries_enforcement_action_ids() -> None:
    decision_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    action_ids = (uuid.uuid4(), uuid.uuid4())
    key = CorrelationKey(
        decision_id=decision_id,
        correlation_id=correlation_id,
        request_id="req-1",
        enforcement_action_ids=action_ids,
    )
    assert key.decision_id == decision_id
    assert key.correlation_id == correlation_id
    assert key.enforcement_action_ids == action_ids
    # Two calls construct equal keys (frozen + hashable).
    same = CorrelationKey(
        decision_id=decision_id,
        correlation_id=correlation_id,
        request_id="req-1",
        enforcement_action_ids=action_ids,
    )
    assert key == same


# ─── Replay-style integration: decision_id stability via seed ─────────


def test_seeded_decision_id_can_be_used_for_replay_assertions() -> None:
    from datetime import datetime, timezone

    from app.governance.decisions import (
        PolicyEvaluationResult,
        build_decision,
    )
    from app.governance.enums import Decision, EnforcementStage

    seed = "test.replay.case-1"
    fixed_id = derive_decision_id(seed=seed)
    fixed_ts = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)

    results = (
        PolicyEvaluationResult(
            policy_name="p",
            rule_id="r",
            decision=Decision.ALLOW,
            reason="r",
        ),
    )
    a = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id="chain.test",
        evaluation_results=results,
        decision_id=fixed_id,
        decided_at=fixed_ts,
    )
    b = build_decision(
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_chain_id="chain.test",
        evaluation_results=results,
        decision_id=fixed_id,
        decided_at=fixed_ts,
    )
    # Same seed + same results -> byte-identical decisions for replay.
    assert a == b
    assert a.decision_id == fixed_id
