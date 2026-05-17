"""Hardening-substrate wire-format vocabulary.

The hardening substrate is **observational**. Every vocabulary
below is descriptive — none of it instructs the runtime to do
something. The substrate may detect, validate, audit, and
classify; it never executes, routes, mutates, or auto-recovers.

Every wire value is pinned. `tests/test_hardening_invariants.py`
pins the catalogue so any rename fails at import.
"""

from __future__ import annotations

from enum import StrEnum


class HardeningFindingKind(StrEnum):
    """Closed vocabulary for hardening-validator findings.

    All findings are observational. They never imply automatic
    correction. The substrate's only output is an inspectable
    record.
    """

    OK = "ok"
    AUTHORITY_OVERLAP = "authority_overlap"
    AUTHORITY_VIOLATION = "authority_violation"
    LINEAGE_CYCLE = "lineage_cycle"
    LINEAGE_GAP = "lineage_gap"
    LINEAGE_DRIFT = "lineage_drift"
    REPLAY_DRIFT = "replay_drift"
    RECONSTRUCTION_DRIFT = "reconstruction_drift"
    ORDERING_NONDETERMINISM = "ordering_nondeterminism"
    REGISTRY_NONDETERMINISM = "registry_nondeterminism"
    CONTAMINATION_IMPORT = "contamination_import"
    CONTAMINATION_SURFACE = "contamination_surface"
    DEPENDENCY_CYCLE = "dependency_cycle"
    DEPENDENCY_VIOLATION = "dependency_violation"
    SURVIVABILITY_GAP = "survivability_gap"
    PERSISTENCE_DISCONTINUITY = "persistence_discontinuity"
    FAILURE_CONTAINMENT_BREACH = "failure_containment_breach"
    INVARIANT_VIOLATION = "invariant_violation"


class HardeningSeverity(StrEnum):
    """Bounded severity classification."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class HardeningStatus(StrEnum):
    """Lifecycle of a hardening audit."""

    PENDING = "pending"
    COMPLETED = "completed"
    INCONCLUSIVE = "inconclusive"
    ERRORED = "errored"


class IntegrityStatus(StrEnum):
    """Outcome of an integrity validation call."""

    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


class ReplayStatus(StrEnum):
    """Outcome of a replay-integrity validation call."""

    BYTE_IDENTICAL = "byte_identical"
    SEMANTIC_EQUIVALENT = "semantic_equivalent"
    DRIFTED = "drifted"
    UNRECONSTRUCTABLE = "unreconstructable"


class SurvivabilityStatus(StrEnum):
    """Outcome of a survivability validation call."""

    SURVIVED = "survived"
    PARTIALLY_SURVIVED = "partially_survived"
    LOST = "lost"
    UNVERIFIABLE = "unverifiable"


class FailureClassification(StrEnum):
    """Bounded vocabulary for substrate-failure classification.

    Failures are **classified**, not handled. The substrate
    refuses to take recovery action.
    """

    BOUNDED = "bounded"
    SUBSTRATE_LOCAL = "substrate_local"
    CROSS_SUBSTRATE = "cross_substrate"
    PERSISTENCE = "persistence"
    LINEAGE = "lineage"
    AUTHORITY = "authority"
    UNCLASSIFIED = "unclassified"


class ContainmentClassification(StrEnum):
    """Whether a failure was contained inside its semantic boundary."""

    CONTAINED = "contained"
    LEAKED = "leaked"
    UNVERIFIABLE = "unverifiable"


class HardeningTraceKind(StrEnum):
    """Trace classification — one entry per runtime method."""

    VALIDATE_AUTHORITY_OWNERSHIP = "validate_authority_ownership"
    VALIDATE_LINEAGE = "validate_lineage"
    VALIDATE_REPLAY = "validate_replay"
    VALIDATE_RECONSTRUCTION = "validate_reconstruction"
    VALIDATE_ORDERING = "validate_ordering"
    DETECT_CONTAMINATION = "detect_contamination"
    AUDIT_DEPENDENCIES = "audit_dependencies"
    VALIDATE_SURVIVABILITY = "validate_survivability"
    RECORD_FAILURE = "record_failure"
    CLASSIFY_CONTAINMENT = "classify_containment"
    AUDIT_RUN = "audit_run"


class SubstrateName(StrEnum):
    """Canonical substrate names — pinned vocabulary.

    Hardening declares ownership boundaries against this enum so
    a typo in a substrate name fails at import.
    """

    AGENTS = "agents"
    ARBITRATION = "arbitration"
    BOUNDARY = "boundary"
    BOUNDARY_TRANSLATION = "boundary_translation"
    BOUNDARY_VOICE = "boundary_voice"
    COORDINATION = "coordination"
    COORDINATION_POLICY = "coordination_policy"
    COORDINATION_TOPOLOGY = "coordination_topology"
    GOVERNANCE = "governance"
    HUMAN = "human"
    MEMORY = "memory"
    ORGANIZATIONAL_INTELLIGENCE = "organizational_intelligence"
    SESSION = "session"
    SUPERVISOR = "supervisor"


__all__ = [
    "ContainmentClassification",
    "FailureClassification",
    "HardeningFindingKind",
    "HardeningSeverity",
    "HardeningStatus",
    "HardeningTraceKind",
    "IntegrityStatus",
    "ReplayStatus",
    "SubstrateName",
    "SurvivabilityStatus",
]
