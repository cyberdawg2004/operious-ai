"""Pin hardening-substrate wire-format vocabulary."""

from __future__ import annotations

import pytest

from app.hardening.enums import (
    ContainmentClassification,
    FailureClassification,
    HardeningFindingKind,
    HardeningSeverity,
    HardeningStatus,
    HardeningTraceKind,
    IntegrityStatus,
    ReplayStatus,
    SubstrateName,
    SurvivabilityStatus,
)


def test_finding_kind_wire_values_are_pinned() -> None:
    assert {member.value for member in HardeningFindingKind} == {
        "ok",
        "authority_overlap",
        "authority_violation",
        "lineage_cycle",
        "lineage_gap",
        "lineage_drift",
        "replay_drift",
        "reconstruction_drift",
        "ordering_nondeterminism",
        "registry_nondeterminism",
        "contamination_import",
        "contamination_surface",
        "dependency_cycle",
        "dependency_violation",
        "survivability_gap",
        "persistence_discontinuity",
        "failure_containment_breach",
        "invariant_violation",
    }


def test_severity_wire_values_are_pinned() -> None:
    assert {member.value for member in HardeningSeverity} == {
        "info",
        "low",
        "medium",
        "high",
        "critical",
    }


def test_trace_kind_wire_values_are_pinned() -> None:
    assert {member.value for member in HardeningTraceKind} == {
        "validate_authority_ownership",
        "validate_lineage",
        "validate_replay",
        "validate_reconstruction",
        "validate_ordering",
        "detect_contamination",
        "audit_dependencies",
        "validate_survivability",
        "record_failure",
        "classify_containment",
        "audit_run",
    }


def test_substrate_names_wire_values_are_pinned() -> None:
    assert {member.value for member in SubstrateName} == {
        "agents",
        "arbitration",
        "boundary",
        "boundary_translation",
        "boundary_voice",
        "coordination",
        "coordination_policy",
        "coordination_topology",
        "governance",
        "human",
        "memory",
        "organizational_intelligence",
        "session",
        "supervisor",
    }


def test_integrity_replay_survivability_failure_pinned() -> None:
    assert {member.value for member in IntegrityStatus} == {
        "passed",
        "failed",
        "inconclusive",
    }
    assert {member.value for member in ReplayStatus} == {
        "byte_identical",
        "semantic_equivalent",
        "drifted",
        "unreconstructable",
    }
    assert {member.value for member in SurvivabilityStatus} == {
        "survived",
        "partially_survived",
        "lost",
        "unverifiable",
    }
    assert {member.value for member in FailureClassification} == {
        "bounded",
        "substrate_local",
        "cross_substrate",
        "persistence",
        "lineage",
        "authority",
        "unclassified",
    }
    assert {member.value for member in ContainmentClassification} == {
        "contained",
        "leaked",
        "unverifiable",
    }
    assert {member.value for member in HardeningStatus} == {
        "pending",
        "completed",
        "inconclusive",
        "errored",
    }


def test_enums_compare_by_value() -> None:
    with pytest.raises(AttributeError):
        HardeningFindingKind.NEW_INVENTED_VALUE  # type: ignore[attr-defined]
