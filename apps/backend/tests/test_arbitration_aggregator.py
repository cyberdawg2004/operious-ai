"""`build_arbitration_decision` — most-authoritative-wins rules.

Aggregation is the single most semantically loaded piece of L4 —
these tests pin the rule that arbitration interprets conflicts
THROUGH the authority hierarchy and never overrides higher
authority.
"""

from __future__ import annotations

from app.arbitration.enums import (
    ArbitrationAuthorityLevel,
    ArbitrationConflictKind,
    ArbitrationDeadlockKind,
    ArbitrationOutcome,
    ArbitrationVerdictKind,
)
from app.arbitration.identity import (
    derive_conflict_id,
    derive_deadlock_witness_id,
    derive_evaluation_id,
    derive_signal_id,
)
from app.arbitration.models.conflict import ArbitrationConflict
from app.arbitration.models.deadlock import DeadlockWitness
from app.arbitration.models.signal import ArbitrationSignal
from app.arbitration.runtime.aggregator import (
    build_arbitration_decision,
)


def _signal(
    *,
    seed: str,
    authority: ArbitrationAuthorityLevel,
    verdict: ArbitrationVerdictKind,
    source_substrate: str = "demo",
    source_id: str | None = None,
) -> ArbitrationSignal:
    return ArbitrationSignal(
        signal_id=derive_signal_id(seed=seed),
        authority=authority,
        verdict=verdict,
        source_substrate=source_substrate,
        source_id=source_id or seed,
    )


def test_no_signals_is_inconclusive() -> None:
    d = build_arbitration_decision(
        signals=(), conflicts=(), deadlock_witnesses=()
    )
    assert d.outcome is ArbitrationOutcome.ARBITRATION_INCONCLUSIVE
    assert d.prevailing_authority is None


def test_single_signal_resolves_to_that_authority() -> None:
    sig = _signal(
        seed="s1",
        authority=ArbitrationAuthorityLevel.GOVERNANCE,
        verdict=ArbitrationVerdictKind.DENY,
        source_substrate="governance",
    )
    d = build_arbitration_decision(
        signals=(sig,), conflicts=(), deadlock_witnesses=()
    )
    assert d.outcome is ArbitrationOutcome.ARBITRATION_RESOLVED
    assert d.prevailing_authority is not None
    assert (
        d.prevailing_authority.level
        is ArbitrationAuthorityLevel.GOVERNANCE
    )
    assert d.prevailing_authority.verdict == "deny"


def test_governance_overrides_supervisors() -> None:
    """User-spec example: SupA=ESCALATE, SupB=ALLOW, Gov=DENY → governance wins."""
    sup_a = _signal(
        seed="sup_a",
        authority=ArbitrationAuthorityLevel.SUPERVISOR,
        verdict=ArbitrationVerdictKind.ESCALATE,
        source_substrate="supervisor",
    )
    sup_b = _signal(
        seed="sup_b",
        authority=ArbitrationAuthorityLevel.SUPERVISOR,
        verdict=ArbitrationVerdictKind.ALLOW,
        source_substrate="supervisor",
    )
    gov = _signal(
        seed="gov",
        authority=ArbitrationAuthorityLevel.GOVERNANCE,
        verdict=ArbitrationVerdictKind.DENY,
        source_substrate="governance",
    )
    d = build_arbitration_decision(
        signals=(sup_a, sup_b, gov),
        conflicts=(),
        deadlock_witnesses=(),
    )
    assert d.outcome is ArbitrationOutcome.ARBITRATION_RESOLVED
    assert d.prevailing_authority is not None
    assert (
        d.prevailing_authority.level
        is ArbitrationAuthorityLevel.GOVERNANCE
    )
    assert d.prevailing_authority.verdict == "deny"


def test_escalate_at_top_authority_is_escalated_outcome() -> None:
    gov = _signal(
        seed="gov",
        authority=ArbitrationAuthorityLevel.GOVERNANCE,
        verdict=ArbitrationVerdictKind.ESCALATE,
    )
    d = build_arbitration_decision(
        signals=(gov,), conflicts=(), deadlock_witnesses=()
    )
    assert d.outcome is ArbitrationOutcome.ARBITRATION_ESCALATED
    assert d.prevailing_authority is not None


def test_disagreement_at_top_authority_is_conflict() -> None:
    g1 = _signal(
        seed="g1",
        authority=ArbitrationAuthorityLevel.GOVERNANCE,
        verdict=ArbitrationVerdictKind.ALLOW,
        source_id="g1",
    )
    g2 = _signal(
        seed="g2",
        authority=ArbitrationAuthorityLevel.GOVERNANCE,
        verdict=ArbitrationVerdictKind.DENY,
        source_id="g2",
    )
    d = build_arbitration_decision(
        signals=(g1, g2), conflicts=(), deadlock_witnesses=()
    )
    assert d.outcome is ArbitrationOutcome.ARBITRATION_CONFLICT
    assert d.prevailing_authority is None


def test_deadlock_witness_dominates() -> None:
    """Even a clear top-authority verdict yields when a deadlock is witnessed."""
    gov = _signal(
        seed="gov",
        authority=ArbitrationAuthorityLevel.GOVERNANCE,
        verdict=ArbitrationVerdictKind.ALLOW,
    )
    eval_id = derive_evaluation_id(seed="e1")
    witness = DeadlockWitness(
        witness_id=derive_deadlock_witness_id(
            evaluation_id=eval_id,
            kind=ArbitrationDeadlockKind.ITERATION_EXHAUSTED.value,
            ordinal=0,
        ),
        kind=ArbitrationDeadlockKind.ITERATION_EXHAUSTED,
        summary="exhausted",
    )
    d = build_arbitration_decision(
        signals=(gov,),
        conflicts=(),
        deadlock_witnesses=(witness,),
    )
    assert d.outcome is ArbitrationOutcome.ARBITRATION_DEADLOCK
    assert d.prevailing_authority is None


def test_unknown_at_top_authority_is_inconclusive() -> None:
    gov = _signal(
        seed="gov",
        authority=ArbitrationAuthorityLevel.GOVERNANCE,
        verdict=ArbitrationVerdictKind.UNKNOWN,
    )
    d = build_arbitration_decision(
        signals=(gov,), conflicts=(), deadlock_witnesses=()
    )
    assert d.outcome is ArbitrationOutcome.ARBITRATION_INCONCLUSIVE


def test_lower_authority_conflicts_do_not_override_top() -> None:
    gov = _signal(
        seed="gov",
        authority=ArbitrationAuthorityLevel.GOVERNANCE,
        verdict=ArbitrationVerdictKind.ALLOW,
    )
    sup_a = _signal(
        seed="sup_a",
        authority=ArbitrationAuthorityLevel.SUPERVISOR,
        verdict=ArbitrationVerdictKind.PASS,
    )
    sup_b = _signal(
        seed="sup_b",
        authority=ArbitrationAuthorityLevel.SUPERVISOR,
        verdict=ArbitrationVerdictKind.FAIL,
    )
    conflict = ArbitrationConflict(
        conflict_id=derive_conflict_id(seed="c1"),
        kind=ArbitrationConflictKind.SUPERVISOR_DISAGREEMENT,
        participants=(str(sup_a.signal_id), str(sup_b.signal_id)),
    )
    d = build_arbitration_decision(
        signals=(gov, sup_a, sup_b),
        conflicts=(conflict,),
        deadlock_witnesses=(),
    )
    assert d.outcome is ArbitrationOutcome.ARBITRATION_RESOLVED
    assert d.prevailing_authority is not None
    assert (
        d.prevailing_authority.level
        is ArbitrationAuthorityLevel.GOVERNANCE
    )
    # Recorded for audit:
    assert "conflicts recorded" in d.reason


def test_aggregator_is_pure_function() -> None:
    """Calling twice with the same inputs yields equal outputs."""
    gov = _signal(
        seed="gov",
        authority=ArbitrationAuthorityLevel.GOVERNANCE,
        verdict=ArbitrationVerdictKind.DENY,
    )
    d1 = build_arbitration_decision(
        signals=(gov,), conflicts=(), deadlock_witnesses=()
    )
    d2 = build_arbitration_decision(
        signals=(gov,), conflicts=(), deadlock_witnesses=()
    )
    assert d1 == d2
