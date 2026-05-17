"""Pure-validator behaviour tests for the hardening substrate."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.hardening.enums import (
    ContainmentClassification,
    HardeningFindingKind,
    IntegrityStatus,
    ReplayStatus,
    SubstrateName,
    SurvivabilityStatus,
)
from app.hardening.integrity.contamination import (
    detect_contamination,
)
from app.hardening.integrity.dependency import (
    audit_dependencies,
)
from app.hardening.integrity.ordering import validate_ordering
from app.hardening.isolation.containment import (
    classify_containment,
)
from app.hardening.lineage.validator import validate_lineage
from app.hardening.replay.integrity import (
    validate_replay_equivalence,
)
from app.hardening.replay.reconstruction import (
    validate_reconstruction,
)
from app.hardening.semantic.validator import (
    validate_authority_ownership,
)
from app.hardening.survivability.validator import (
    validate_survivability,
)


NOW = datetime.now(UTC)


def test_authority_ownership_emits_violations_for_forbidden_observers() -> (
    None
):
    findings = validate_authority_ownership(
        observed_owners={
            "operational_restrictions": (
                SubstrateName.AGENTS,
                SubstrateName.SUPERVISOR,
            ),
            "memory_evolution": (
                SubstrateName.GOVERNANCE,
            ),
        },
        detected_at=NOW,
    )
    concerns = sorted(f.boundary_concern for f in findings)
    assert concerns == [
        "memory_evolution",
        "operational_restrictions",
        "operational_restrictions",
    ]


def test_authority_ownership_clean_when_only_owner_observed() -> None:
    findings = validate_authority_ownership(
        observed_owners={
            "operational_restrictions": (
                SubstrateName.GOVERNANCE,
            )
        },
        detected_at=NOW,
    )
    assert findings == ()


def test_lineage_detects_cycle_and_gap() -> None:
    findings, status = validate_lineage(
        records=(
            ("a", "b"),
            ("b", "a"),
            ("c", "missing"),
        ),
        seed="lineage",
        detected_at=NOW,
    )
    assert status is IntegrityStatus.FAILED
    kinds = {f.kind for f in findings}
    assert HardeningFindingKind.LINEAGE_CYCLE in kinds
    assert HardeningFindingKind.LINEAGE_GAP in kinds


def test_lineage_clean_when_acyclic_and_complete() -> None:
    findings, status = validate_lineage(
        records=(
            ("root", None),
            ("a", "root"),
            ("b", "a"),
        ),
        seed="lineage",
        detected_at=NOW,
    )
    assert findings == ()
    assert status is IntegrityStatus.PASSED


def test_replay_equivalence_byte_identical() -> None:
    finding = validate_replay_equivalence(
        canonical_payload={"a": 1, "b": [1, 2]},
        candidate_payload={"b": [1, 2], "a": 1},
        seed="rep",
    )
    assert finding.is_byte_identical
    assert finding.diff_summary is None


def test_replay_equivalence_drift() -> None:
    finding = validate_replay_equivalence(
        canonical_payload={"a": 1},
        candidate_payload={"a": 2},
        seed="rep",
    )
    assert finding.status is ReplayStatus.DRIFTED
    assert finding.diff_summary is not None


def test_reconstruction_drift_surfaced() -> None:
    f1 = validate_reconstruction(
        original_payload={"x": 1},
        reconstructed_payload={"x": 1},
        seed="rec",
    )
    assert f1.is_byte_identical
    f2 = validate_reconstruction(
        original_payload={"x": 1},
        reconstructed_payload={"x": 2},
        seed="rec",
    )
    assert f2.status is ReplayStatus.DRIFTED


def test_ordering_passes_when_sorted() -> None:
    findings, status = validate_ordering(
        items=("a", "b", "c"),
        key_fn=lambda x: x,
        seed="ord",
    )
    assert findings == ()
    assert status is IntegrityStatus.PASSED


def test_ordering_fails_when_unsorted() -> None:
    findings, status = validate_ordering(
        items=("b", "a", "c"),
        key_fn=lambda x: x,
        seed="ord",
    )
    assert status is IntegrityStatus.FAILED
    assert findings[0].kind is (
        HardeningFindingKind.ORDERING_NONDETERMINISM
    )


def test_contamination_detector_with_injected_source() -> None:
    findings, status = detect_contamination(
        substrate=SubstrateName.SUPERVISOR,
        substrate_path="/nonexistent",
        forbidden_module_prefixes=("app.governance",),
        seed="cont",
        source_lines_by_path={
            "supervisor.py": (
                "from app.governance import GovernanceRuntime\n"
                "import other.module\n"
            ),
        },
    )
    assert status is IntegrityStatus.FAILED
    assert (
        findings[0].kind
        is HardeningFindingKind.CONTAMINATION_IMPORT
    )


def test_contamination_detector_clean_when_no_forbidden_imports() -> (
    None
):
    findings, status = detect_contamination(
        substrate=SubstrateName.SUPERVISOR,
        substrate_path="/nonexistent",
        forbidden_module_prefixes=("app.governance",),
        seed="cont",
        source_lines_by_path={
            "supervisor.py": "from app.supervisor import x\n",
        },
    )
    assert status is IntegrityStatus.PASSED
    assert findings == ()


def test_dependency_auditor_flags_forbidden_edges() -> None:
    finding = audit_dependencies(
        substrate_paths=(
            (SubstrateName.AGENTS, "/agents"),
            (SubstrateName.GOVERNANCE, "/governance"),
        ),
        forbidden_edges=(
            (SubstrateName.AGENTS, SubstrateName.GOVERNANCE),
        ),
        seed="dep",
        source_lines_by_substrate={
            SubstrateName.AGENTS: {
                "x.py": "from app.governance import G\n",
            },
            SubstrateName.GOVERNANCE: {
                "y.py": "import os\n",
            },
        },
    )
    assert not finding.is_clean
    assert finding.forbidden_edges[0].source == (
        SubstrateName.AGENTS
    )
    assert finding.forbidden_edges[0].target == (
        SubstrateName.GOVERNANCE
    )


def test_classify_containment_logic() -> None:
    assert (
        classify_containment(
            originating_substrate=SubstrateName.AGENTS,
            observers=(SubstrateName.AGENTS,),
        )
        is ContainmentClassification.CONTAINED
    )
    assert (
        classify_containment(
            originating_substrate=SubstrateName.AGENTS,
            observers=(
                SubstrateName.AGENTS,
                SubstrateName.SUPERVISOR,
            ),
        )
        is ContainmentClassification.LEAKED
    )
    assert (
        classify_containment(
            originating_substrate=SubstrateName.AGENTS,
            observers=(),
        )
        is ContainmentClassification.UNVERIFIABLE
    )


def test_survivability_classifier() -> None:
    a = validate_survivability(
        expected_count=10, survived_count=10, seed="s"
    )
    b = validate_survivability(
        expected_count=10, survived_count=0, seed="s"
    )
    c = validate_survivability(
        expected_count=10, survived_count=5, seed="s"
    )
    d = validate_survivability(
        expected_count=0, survived_count=0, seed="s"
    )
    assert a.status is SurvivabilityStatus.SURVIVED
    assert b.status is SurvivabilityStatus.LOST
    assert c.status is SurvivabilityStatus.PARTIALLY_SURVIVED
    assert d.status is SurvivabilityStatus.UNVERIFIABLE


def test_validators_reject_naive_timestamps() -> None:
    with pytest.raises(ValueError):
        validate_authority_ownership(
            observed_owners={},
            detected_at=datetime(2025, 1, 1),
        )
    with pytest.raises(ValueError):
        validate_lineage(
            records=(),
            seed="x",
            detected_at=datetime(2025, 1, 1),
        )
