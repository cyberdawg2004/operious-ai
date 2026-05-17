"""Operational arbitration enum vocabulary — pinned wire-format values.

Four typed vocabularies the arbitration substrate speaks in. All
`StrEnum` so JSON round-trips are transparent and the persistence
layer can store the string value verbatim.

Wire-format discipline: every value below is pinned. Renaming a
value is a breaking change to every previously persisted arbitration
record. `tests/test_arbitration_invariants.py` pins the catalogue
so accidental drift fails at import time.

Critical architectural rule (Sprint L4 Final Directive):

* Arbitration is **interpretive authority**, NOT execution authority.
* The verdict vocabulary below describes WHAT the substrate observed
  about a signal; it never instructs WHAT to do next.
* Outcomes describe HOW the substrate interpreted the case; they
  never schedule re-evaluation, retries, or recovery.
"""

from __future__ import annotations

from enum import StrEnum


class ArbitrationAuthorityLevel(StrEnum):
    """Authority precedence — explicit, static, deterministic.

    Sprint L4 critical authority hierarchy:

        GOVERNANCE  > TOPOLOGY  > POLICY  >
        ARBITRATION > SUPERVISOR > EXECUTION

    Arbitration interprets conflicts THROUGH this hierarchy. It
    NEVER overrides higher authority. Precedence ordering is encoded
    in `arbitration_authority_precedence` in
    `app.arbitration.taxonomy`; no other layer re-encodes it.

    The substrate enum values are deliberately lowercase so they
    round-trip identically when nested into JSON payloads alongside
    sibling-substrate enums (`coordination.*`, `governance.*`,
    `coordination.topology.*`, …).
    """

    GOVERNANCE = "governance"
    TOPOLOGY = "topology"
    POLICY = "policy"
    ARBITRATION = "arbitration"
    SUPERVISOR = "supervisor"
    EXECUTION = "execution"


class ArbitrationOutcome(StrEnum):
    """Terminal outcome of one `OperationalArbitrationRuntime.evaluate()` call.

    The outcome is purely interpretive. It does NOT dispatch,
    retry, repair, or instruct any downstream runtime.

    ARBITRATION_RESOLVED       — the substrate resolved the case
                                  deterministically using authority
                                  precedence. A single prevailing
                                  authority is identified; conflicts
                                  (if any) are recorded as audit
                                  artifacts.
    ARBITRATION_ESCALATED      — the prevailing authority's signal
                                  itself carries an escalation
                                  verdict. Surfaced as a distinct
                                  outcome so callers can tell
                                  "case resolved, do nothing" apart
                                  from "case resolved, an external
                                  escalation pathway is implied".
    ARBITRATION_INCONCLUSIVE   — no prevailing authority emerged
                                  (no signals at all, or signals
                                  exist but none reach a
                                  classifiable verdict).
    ARBITRATION_DEADLOCK       — the deadlock-detection evaluator
                                  surfaced a bounded deadlock
                                  pattern (e.g. iteration count
                                  exhausted). Detection only —
                                  arbitration does NOT recover.
    ARBITRATION_CONFLICT       — signals at the same (highest)
                                  authority level disagree; the
                                  substrate refuses to elect a
                                  winner. The audit trail records
                                  every contradiction.
    ARBITRATION_ERROR          — the substrate itself failed (an
                                  evaluator raised, the request was
                                  malformed, persistence failed).
                                  Distinct from CONFLICT /
                                  DEADLOCK / INCONCLUSIVE — those
                                  are *correct* interpretations of
                                  hard cases; ERROR is a substrate
                                  malfunction.
    """

    ARBITRATION_RESOLVED = "arbitration_resolved"
    ARBITRATION_ESCALATED = "arbitration_escalated"
    ARBITRATION_INCONCLUSIVE = "arbitration_inconclusive"
    ARBITRATION_DEADLOCK = "arbitration_deadlock"
    ARBITRATION_CONFLICT = "arbitration_conflict"
    ARBITRATION_ERROR = "arbitration_error"


class ArbitrationVerdictKind(StrEnum):
    """Closed vocabulary for what an input signal asserts.

    Adding a value is a deliberate vocabulary change. Downstream
    consumers (audit / supervisor surfaces) MUST treat unknown
    values fail-safe.

    The vocabulary deliberately covers two related but distinct
    semantic axes:

    * **Authorisation verdicts**: ALLOW, DENY, ESCALATE, DEGRADE.
      These describe whether downstream activity may proceed.
    * **Quality verdicts**: PASS, FAIL, SAFE, UNSAFE, VALID,
      INVALID, WARN. These describe a substrate's *judgment* on
      observed behaviour, independent of authorisation.

    Contradictions can arise WITHIN an axis (PASS vs FAIL) or
    BETWEEN axes (ALLOW vs UNSAFE). The arbitration evaluators
    detect both classes deterministically.

    UNKNOWN is a sentinel; it appears when a substrate emits a
    signal whose verdict was not classified before arbitration ran.
    """

    ALLOW = "allow"
    DENY = "deny"
    ESCALATE = "escalate"
    DEGRADE = "degrade"
    PASS = "pass"
    FAIL = "fail"
    SAFE = "safe"
    UNSAFE = "unsafe"
    VALID = "valid"
    INVALID = "invalid"
    WARN = "warn"
    UNKNOWN = "unknown"


class ArbitrationConflictKind(StrEnum):
    """Classification of a detected contradiction between signals.

    Closed set — adding a value is a deliberate vocabulary change.

    AUTHORISATION_CONFLICT       — ALLOW vs DENY / ESCALATE.
    QUALITY_CONFLICT             — PASS vs FAIL, SAFE vs UNSAFE,
                                    VALID vs INVALID.
    AUTHORISATION_QUALITY_CROSS  — an authorisation verdict
                                    contradicts a quality verdict
                                    (e.g. ALLOW vs UNSAFE). Surfaces
                                    these explicitly because they
                                    indicate a more dangerous class
                                    of disagreement (the system is
                                    permitting unsafe behaviour or
                                    blocking safe behaviour).
    ESCALATION_CONFLICT          — ESCALATE vs ALLOW, or ESCALATE
                                    vs ESCALATE with different
                                    target authorities.
    SUPERVISOR_DISAGREEMENT      — two supervisor signals with
                                    differing verdicts. Surfaces as
                                    its own kind because supervisors
                                    are *read-only* — the disagreement
                                    is itself the operational state
                                    to inspect.
    RECOMMENDATION_CONFLICT      — two recommendations whose
                                    `directive`s contradict.
    """

    AUTHORISATION_CONFLICT = "authorisation_conflict"
    QUALITY_CONFLICT = "quality_conflict"
    AUTHORISATION_QUALITY_CROSS = "authorisation_quality_cross"
    ESCALATION_CONFLICT = "escalation_conflict"
    SUPERVISOR_DISAGREEMENT = "supervisor_disagreement"
    RECOMMENDATION_CONFLICT = "recommendation_conflict"


class ArbitrationDeadlockKind(StrEnum):
    """Classification of a detected deadlock pattern.

    Closed set. Detection only — arbitration NEVER recovers.

    ITERATION_EXHAUSTED          — the case has been arbitrated more
                                    than its `max_iterations`
                                    threshold; the same conflict
                                    keeps recurring.
    REPEATED_BLOCKED_STATE       — the case's prior arbitrations all
                                    resolved to a blocking outcome
                                    with the same signature; no
                                    forward progress is possible
                                    without external intervention.
    CONTRADICTORY_ESCALATION_CHAIN
                                  — the escalation lineage of the
                                    case contains contradictory
                                    escalation verdicts (e.g.
                                    escalate-to-A and escalate-to-B
                                    simultaneously).
    CYCLIC_CASE_LINEAGE          — the case's `prior_case_ids`
                                    contains a duplicate id; the
                                    arbitration history references
                                    itself.
    """

    ITERATION_EXHAUSTED = "iteration_exhausted"
    REPEATED_BLOCKED_STATE = "repeated_blocked_state"
    CONTRADICTORY_ESCALATION_CHAIN = "contradictory_escalation_chain"
    CYCLIC_CASE_LINEAGE = "cyclic_case_lineage"


__all__ = [
    "ArbitrationAuthorityLevel",
    "ArbitrationOutcome",
    "ArbitrationVerdictKind",
    "ArbitrationConflictKind",
    "ArbitrationDeadlockKind",
]
