"""Canonical arbitration vocabulary + authority precedence.

Three complementary catalogues + one authority-precedence table:

* `ArbitrationFindingCode`        — stable finding codes emitted by
                                     the built-in evaluators.
* `ArbitrationMetadataKey`        — canonical keys the substrate
                                     writes onto envelopes / traces.
* Authority precedence            — the single authority on
                                     "most-authoritative wins".
                                     `arbitration_authority_precedence`,
                                     `is_higher_authority`,
                                     `compare_authority` are the
                                     only callers should use; no
                                     other layer re-encodes the
                                     precedence.
* Verdict classification helpers  — pure functions over
                                     `ArbitrationVerdictKind` that
                                     answer "is this an
                                     authorisation verdict?" / "is
                                     this a quality verdict?" /
                                     "does verdict A contradict
                                     verdict B?".

External evaluators may emit codes outside the `FindingCode` enum;
audit / supervisor surfaces treat unknown codes fail-safe.
"""

from __future__ import annotations

from enum import StrEnum

from app.arbitration.enums import (
    ArbitrationAuthorityLevel,
    ArbitrationVerdictKind,
)


class ArbitrationFindingCode(StrEnum):
    """Stable codes emitted by the built-in arbitration evaluators."""

    # ─── Apex decision codes (runtime-emitted) ───────────────────────
    AUTHORITY_PRECEDENCE_APPLIED = "arbitration.authority_precedence_applied"
    RESOLUTION_INCONCLUSIVE = "arbitration.resolution_inconclusive"
    NO_CONFLICT = "arbitration.no_conflict"
    INSUFFICIENT_SIGNALS = "arbitration.insufficient_signals"

    # ─── Conflict codes ──────────────────────────────────────────────
    CONTRADICTORY_FINDINGS = "arbitration.contradictory_findings"
    CONFLICTING_RECOMMENDATIONS = "arbitration.conflicting_recommendations"
    ESCALATION_CONFLICT = "arbitration.escalation_conflict"
    SUPERVISOR_DISAGREEMENT = "arbitration.supervisor_disagreement"
    AUTHORISATION_QUALITY_CROSS = "arbitration.authorisation_quality_cross"

    # ─── Deadlock codes ──────────────────────────────────────────────
    DEADLOCK_DETECTED = "arbitration.deadlock_detected"
    DEADLOCK_RISK = "arbitration.deadlock_risk"


class ArbitrationMetadataKey(StrEnum):
    """Canonical metadata keys the substrate writes onto envelopes / traces.

    Namespaced under ``arbitration.*`` so they don't collide with
    caller-supplied free-form metadata or with sibling substrate
    namespaces (``coordination.*``, ``coordination.policy.*``,
    ``coordination.topology.*``).
    """

    CASE_ID = "arbitration.case_id"
    EVALUATION_ID = "arbitration.evaluation_id"
    CHAIN_ID = "arbitration.chain_id"
    OUTCOME = "arbitration.outcome"
    PREVAILING_AUTHORITY = "arbitration.prevailing_authority"
    PREVAILING_SOURCE_ID = "arbitration.prevailing_source_id"
    EVALUATOR_NAMES = "arbitration.evaluator_names"
    FINDING_COUNT = "arbitration.finding_count"
    CONFLICT_COUNT = "arbitration.conflict_count"
    DEADLOCK_WITNESS_COUNT = "arbitration.deadlock_witness_count"
    SIGNAL_COUNT = "arbitration.signal_count"
    RECOMMENDATION_COUNT = "arbitration.recommendation_count"
    ITERATION_COUNT = "arbitration.iteration_count"
    MAX_ITERATIONS = "arbitration.max_iterations"


# ─── Authority precedence ────────────────────────────────────────────


# Lower number = MORE authoritative. Hard-coded to enforce the
# semantic hierarchy:
#
#   GOVERNANCE > TOPOLOGY > POLICY > ARBITRATION > SUPERVISOR > EXECUTION
#
# The arbitration substrate's OWN findings are issued at
# `ARBITRATION` precedence — strictly LOWER than the substrates whose
# verdicts it interprets (governance / topology / policy). This is
# the structural guarantee that arbitration cannot override higher
# authority.
_AUTHORITY_PRECEDENCE: dict[ArbitrationAuthorityLevel, int] = {
    ArbitrationAuthorityLevel.GOVERNANCE: 0,
    ArbitrationAuthorityLevel.TOPOLOGY: 1,
    ArbitrationAuthorityLevel.POLICY: 2,
    ArbitrationAuthorityLevel.ARBITRATION: 3,
    ArbitrationAuthorityLevel.SUPERVISOR: 4,
    ArbitrationAuthorityLevel.EXECUTION: 5,
}


def arbitration_authority_precedence(
    level: ArbitrationAuthorityLevel,
) -> int:
    """Return an integer score; lower number = MORE authoritative."""
    return _AUTHORITY_PRECEDENCE[level]


def is_higher_authority(
    a: ArbitrationAuthorityLevel,
    b: ArbitrationAuthorityLevel,
) -> bool:
    """True iff `a` is strictly more authoritative than `b`."""
    return _AUTHORITY_PRECEDENCE[a] < _AUTHORITY_PRECEDENCE[b]


def compare_authority(
    a: ArbitrationAuthorityLevel,
    b: ArbitrationAuthorityLevel,
) -> int:
    """Negative if `a` more authoritative than `b`; positive if less; 0 equal."""
    return _AUTHORITY_PRECEDENCE[a] - _AUTHORITY_PRECEDENCE[b]


# ─── Verdict classification ──────────────────────────────────────────


_AUTHORISATION_VERDICTS: frozenset[ArbitrationVerdictKind] = frozenset(
    {
        ArbitrationVerdictKind.ALLOW,
        ArbitrationVerdictKind.DENY,
        ArbitrationVerdictKind.ESCALATE,
        ArbitrationVerdictKind.DEGRADE,
    }
)


_QUALITY_VERDICTS: frozenset[ArbitrationVerdictKind] = frozenset(
    {
        ArbitrationVerdictKind.PASS,
        ArbitrationVerdictKind.FAIL,
        ArbitrationVerdictKind.SAFE,
        ArbitrationVerdictKind.UNSAFE,
        ArbitrationVerdictKind.VALID,
        ArbitrationVerdictKind.INVALID,
        ArbitrationVerdictKind.WARN,
    }
)


# Explicit, pinned contradiction table: A vs B form a contradiction
# iff the unordered pair appears in this set. Permissive omissions
# (e.g. WARN vs PASS) are NOT contradictions — they are advisory.
_CONTRADICTIONS: frozenset[
    frozenset[ArbitrationVerdictKind]
] = frozenset(
    {
        frozenset(
            {
                ArbitrationVerdictKind.ALLOW,
                ArbitrationVerdictKind.DENY,
            }
        ),
        frozenset(
            {
                ArbitrationVerdictKind.ALLOW,
                ArbitrationVerdictKind.ESCALATE,
            }
        ),
        frozenset(
            {
                ArbitrationVerdictKind.PASS,
                ArbitrationVerdictKind.FAIL,
            }
        ),
        frozenset(
            {
                ArbitrationVerdictKind.SAFE,
                ArbitrationVerdictKind.UNSAFE,
            }
        ),
        frozenset(
            {
                ArbitrationVerdictKind.VALID,
                ArbitrationVerdictKind.INVALID,
            }
        ),
    }
)


# Authorisation–quality crosses: an authorisation verdict
# contradicts a quality verdict only on these explicit pairs. Used
# by `is_cross_axis_contradiction` for the
# `AUTHORISATION_QUALITY_CROSS` classification.
_CROSS_AXIS: frozenset[
    frozenset[ArbitrationVerdictKind]
] = frozenset(
    {
        frozenset(
            {
                ArbitrationVerdictKind.ALLOW,
                ArbitrationVerdictKind.UNSAFE,
            }
        ),
        frozenset(
            {
                ArbitrationVerdictKind.ALLOW,
                ArbitrationVerdictKind.FAIL,
            }
        ),
        frozenset(
            {
                ArbitrationVerdictKind.ALLOW,
                ArbitrationVerdictKind.INVALID,
            }
        ),
        frozenset(
            {
                ArbitrationVerdictKind.DENY,
                ArbitrationVerdictKind.SAFE,
            }
        ),
        frozenset(
            {
                ArbitrationVerdictKind.DENY,
                ArbitrationVerdictKind.PASS,
            }
        ),
        frozenset(
            {
                ArbitrationVerdictKind.DENY,
                ArbitrationVerdictKind.VALID,
            }
        ),
    }
)


def is_authorisation_verdict(
    verdict: ArbitrationVerdictKind,
) -> bool:
    return verdict in _AUTHORISATION_VERDICTS


def is_quality_verdict(verdict: ArbitrationVerdictKind) -> bool:
    return verdict in _QUALITY_VERDICTS


def is_contradiction(
    a: ArbitrationVerdictKind,
    b: ArbitrationVerdictKind,
) -> bool:
    """True iff verdicts `a` and `b` are direct contradictions."""
    return frozenset({a, b}) in _CONTRADICTIONS


def is_cross_axis_contradiction(
    a: ArbitrationVerdictKind,
    b: ArbitrationVerdictKind,
) -> bool:
    """True iff verdicts `a` and `b` contradict across axes (auth vs quality)."""
    return frozenset({a, b}) in _CROSS_AXIS


__all__ = [
    "ArbitrationFindingCode",
    "ArbitrationMetadataKey",
    "arbitration_authority_precedence",
    "compare_authority",
    "is_higher_authority",
    "is_authorisation_verdict",
    "is_quality_verdict",
    "is_contradiction",
    "is_cross_axis_contradiction",
]
