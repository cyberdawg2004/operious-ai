"""Wire-format pinning for arbitration enums.

Renaming a value here is a breaking persistence change. This test
suite guards against accidental drift.
"""

from __future__ import annotations

from app.arbitration.enums import (
    ArbitrationAuthorityLevel,
    ArbitrationConflictKind,
    ArbitrationDeadlockKind,
    ArbitrationOutcome,
    ArbitrationVerdictKind,
)


# ─── ArbitrationAuthorityLevel ───────────────────────────────────────


_AUTHORITY_WIRE_VALUES: dict[ArbitrationAuthorityLevel, str] = {
    ArbitrationAuthorityLevel.GOVERNANCE: "governance",
    ArbitrationAuthorityLevel.TOPOLOGY: "topology",
    ArbitrationAuthorityLevel.POLICY: "policy",
    ArbitrationAuthorityLevel.ARBITRATION: "arbitration",
    ArbitrationAuthorityLevel.SUPERVISOR: "supervisor",
    ArbitrationAuthorityLevel.EXECUTION: "execution",
}


def test_authority_wire_values_pinned() -> None:
    for member, expected in _AUTHORITY_WIRE_VALUES.items():
        assert member.value == expected
    assert set(ArbitrationAuthorityLevel) == set(
        _AUTHORITY_WIRE_VALUES.keys()
    )


# ─── ArbitrationOutcome ──────────────────────────────────────────────


_OUTCOME_WIRE_VALUES: dict[ArbitrationOutcome, str] = {
    ArbitrationOutcome.ARBITRATION_RESOLVED: "arbitration_resolved",
    ArbitrationOutcome.ARBITRATION_ESCALATED: "arbitration_escalated",
    ArbitrationOutcome.ARBITRATION_INCONCLUSIVE: "arbitration_inconclusive",
    ArbitrationOutcome.ARBITRATION_DEADLOCK: "arbitration_deadlock",
    ArbitrationOutcome.ARBITRATION_CONFLICT: "arbitration_conflict",
    ArbitrationOutcome.ARBITRATION_ERROR: "arbitration_error",
}


def test_outcome_wire_values_pinned() -> None:
    for member, expected in _OUTCOME_WIRE_VALUES.items():
        assert member.value == expected
    assert set(ArbitrationOutcome) == set(_OUTCOME_WIRE_VALUES.keys())


# ─── ArbitrationVerdictKind ──────────────────────────────────────────


_VERDICT_WIRE_VALUES: dict[ArbitrationVerdictKind, str] = {
    ArbitrationVerdictKind.ALLOW: "allow",
    ArbitrationVerdictKind.DENY: "deny",
    ArbitrationVerdictKind.ESCALATE: "escalate",
    ArbitrationVerdictKind.DEGRADE: "degrade",
    ArbitrationVerdictKind.PASS: "pass",
    ArbitrationVerdictKind.FAIL: "fail",
    ArbitrationVerdictKind.SAFE: "safe",
    ArbitrationVerdictKind.UNSAFE: "unsafe",
    ArbitrationVerdictKind.VALID: "valid",
    ArbitrationVerdictKind.INVALID: "invalid",
    ArbitrationVerdictKind.WARN: "warn",
    ArbitrationVerdictKind.UNKNOWN: "unknown",
}


def test_verdict_wire_values_pinned() -> None:
    for member, expected in _VERDICT_WIRE_VALUES.items():
        assert member.value == expected
    assert set(ArbitrationVerdictKind) == set(
        _VERDICT_WIRE_VALUES.keys()
    )


# ─── ArbitrationConflictKind ─────────────────────────────────────────


_CONFLICT_WIRE_VALUES: dict[ArbitrationConflictKind, str] = {
    ArbitrationConflictKind.AUTHORISATION_CONFLICT: "authorisation_conflict",
    ArbitrationConflictKind.QUALITY_CONFLICT: "quality_conflict",
    ArbitrationConflictKind.AUTHORISATION_QUALITY_CROSS: "authorisation_quality_cross",
    ArbitrationConflictKind.ESCALATION_CONFLICT: "escalation_conflict",
    ArbitrationConflictKind.SUPERVISOR_DISAGREEMENT: "supervisor_disagreement",
    ArbitrationConflictKind.RECOMMENDATION_CONFLICT: "recommendation_conflict",
}


def test_conflict_kind_wire_values_pinned() -> None:
    for member, expected in _CONFLICT_WIRE_VALUES.items():
        assert member.value == expected
    assert set(ArbitrationConflictKind) == set(
        _CONFLICT_WIRE_VALUES.keys()
    )


# ─── ArbitrationDeadlockKind ─────────────────────────────────────────


_DEADLOCK_WIRE_VALUES: dict[ArbitrationDeadlockKind, str] = {
    ArbitrationDeadlockKind.ITERATION_EXHAUSTED: "iteration_exhausted",
    ArbitrationDeadlockKind.REPEATED_BLOCKED_STATE: "repeated_blocked_state",
    ArbitrationDeadlockKind.CONTRADICTORY_ESCALATION_CHAIN: "contradictory_escalation_chain",
    ArbitrationDeadlockKind.CYCLIC_CASE_LINEAGE: "cyclic_case_lineage",
}


def test_deadlock_kind_wire_values_pinned() -> None:
    for member, expected in _DEADLOCK_WIRE_VALUES.items():
        assert member.value == expected
    assert set(ArbitrationDeadlockKind) == set(
        _DEADLOCK_WIRE_VALUES.keys()
    )
