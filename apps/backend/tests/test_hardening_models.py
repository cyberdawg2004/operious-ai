"""Validate hardening domain-model invariants."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.hardening.enums import (
    ContainmentClassification,
    FailureClassification,
    HardeningFindingKind,
    HardeningSeverity,
    HardeningStatus,
    HardeningTraceKind,
    SubstrateName,
    SurvivabilityStatus,
)
from app.hardening.identity import (
    derive_audit_id,
    derive_failure_record_id,
    derive_finding_id,
    derive_violation_id,
    generate_correlation_id,
)
from app.hardening.models import (
    AuthorityOwnershipMap,
    BoundaryViolationFinding,
    DependencyAuditFinding,
    DependencyEdge,
    FailureContainmentRecord,
    HardeningAudit,
    HardeningFinding,
    SemanticAuthorityBoundary,
    SemanticContainmentTrace,
    SurvivabilityFinding,
)
from app.hardening.models.ownership import (
    CANONICAL_AUTHORITY_OWNERSHIP_MAP,
)


NOW = datetime.now(UTC)


def _finding(ordinal: int = 0) -> HardeningFinding:
    return HardeningFinding(
        finding_id=derive_finding_id(
            audit_seed="seed",
            kind="ok",
            ordinal=ordinal,
        ),
        ordinal=ordinal,
        kind=HardeningFindingKind.OK,
        severity=HardeningSeverity.INFO,
        summary="ok",
        detected_at=NOW,
    )


def test_finding_requires_summary_and_tz_aware() -> None:
    with pytest.raises(ValueError):
        HardeningFinding(
            finding_id=derive_finding_id(
                audit_seed="seed", kind="ok", ordinal=0
            ),
            ordinal=0,
            kind=HardeningFindingKind.OK,
            severity=HardeningSeverity.INFO,
            summary="",
            detected_at=NOW,
        )
    with pytest.raises(ValueError):
        HardeningFinding(
            finding_id=derive_finding_id(
                audit_seed="seed", kind="ok", ordinal=0
            ),
            ordinal=0,
            kind=HardeningFindingKind.OK,
            severity=HardeningSeverity.INFO,
            summary="x",
            detected_at=datetime(2025, 1, 1),
        )


def test_audit_findings_must_be_strictly_monotonic() -> None:
    with pytest.raises(ValueError):
        HardeningAudit(
            audit_id=derive_audit_id(seed="x"),
            seed="x",
            kind=HardeningTraceKind.AUDIT_RUN,
            status=HardeningStatus.COMPLETED,
            findings=(_finding(0), _finding(0)),
            started_at=NOW,
            ended_at=NOW,
        )


def test_audit_clean_when_no_findings() -> None:
    a = HardeningAudit(
        audit_id=derive_audit_id(seed="y"),
        seed="y",
        kind=HardeningTraceKind.AUDIT_RUN,
        status=HardeningStatus.COMPLETED,
        findings=(),
        started_at=NOW,
        ended_at=NOW,
    )
    assert a.is_clean


def test_authority_ownership_map_rejects_duplicates() -> None:
    with pytest.raises(ValueError):
        AuthorityOwnershipMap(
            boundaries=(
                SemanticAuthorityBoundary(
                    boundary_id=derive_finding_id(
                        audit_seed="x",
                        kind="b1",
                        ordinal=0,
                    ),  # type: ignore[arg-type]
                    concern="restrictions",
                    owner=SubstrateName.GOVERNANCE,
                    description="x",
                ),
                SemanticAuthorityBoundary(
                    boundary_id=derive_finding_id(
                        audit_seed="x",
                        kind="b2",
                        ordinal=0,
                    ),  # type: ignore[arg-type]
                    concern="restrictions",
                    owner=SubstrateName.AGENTS,
                    description="x",
                ),
            )
        )


def test_canonical_map_iteration_is_sorted_and_complete() -> None:
    concerns = CANONICAL_AUTHORITY_OWNERSHIP_MAP.concerns()
    assert list(concerns) == sorted(concerns)
    assert (
        CANONICAL_AUTHORITY_OWNERSHIP_MAP.owner_for(
            "operational_restrictions"
        )
        is SubstrateName.GOVERNANCE
    )
    assert (
        CANONICAL_AUTHORITY_OWNERSHIP_MAP.owner_for(
            "memory_evolution"
        )
        is SubstrateName.ORGANIZATIONAL_INTELLIGENCE
    )
    boundary = CANONICAL_AUTHORITY_OWNERSHIP_MAP.boundary_for(
        "operational_approval"
    )
    assert boundary is not None
    assert SubstrateName.AGENTS in boundary.forbidden_owners


def test_boundary_violation_rejects_self_offence() -> None:
    with pytest.raises(ValueError):
        BoundaryViolationFinding(
            violation_id=derive_violation_id(
                boundary_concern="approval",
                offender="governance",
                detail="x",
            ),
            boundary_concern="approval",
            rightful_owner=SubstrateName.GOVERNANCE,
            offender=SubstrateName.GOVERNANCE,
            offender_location=None,
            severity=HardeningSeverity.HIGH,
            summary="self",
            detected_at=NOW,
        )


def test_dependency_edge_validates() -> None:
    with pytest.raises(ValueError):
        DependencyEdge(
            source=SubstrateName.AGENTS,
            target=SubstrateName.AGENTS,
            occurrences=1,
        )
    with pytest.raises(ValueError):
        DependencyEdge(
            source=SubstrateName.AGENTS,
            target=SubstrateName.GOVERNANCE,
            occurrences=0,
        )


def test_dependency_audit_finding_clean() -> None:
    finding = DependencyAuditFinding(
        finding_id=derive_finding_id(
            audit_seed="dep",
            kind="dependency_audit",
            ordinal=0,
        ),
        audit_id=derive_audit_id(seed="dep"),
        edges=(),
        forbidden_edges=(),
        severity=HardeningSeverity.INFO,
        summary="0 edges",
        detected_at=NOW,
    )
    assert finding.is_clean


def test_failure_record_validates() -> None:
    record = FailureContainmentRecord(
        record_id=derive_failure_record_id(seed="x"),
        substrate=SubstrateName.AGENTS,
        classification=FailureClassification.SUBSTRATE_LOCAL,
        containment=ContainmentClassification.CONTAINED,
        severity=HardeningSeverity.MEDIUM,
        summary="bounded",
        recorded_at=NOW,
        error_class_name="ValueError",
    )
    assert record.summary == "bounded"


def test_survivability_invariants() -> None:
    with pytest.raises(ValueError):
        SurvivabilityFinding(
            finding_id=derive_finding_id(
                audit_seed="s",
                kind="survivability:lost",
                ordinal=0,
            ),
            status=SurvivabilityStatus.LOST,
            survived_count=5,
            expected_count=4,
            scope=None,
            detected_at=NOW,
        )


def test_semantic_containment_trace() -> None:
    trace = SemanticContainmentTrace(
        correlation_id=generate_correlation_id(),
        checked_concerns=(),
        violations=(),
        started_at=NOW,
        ended_at=NOW,
    )
    assert trace.is_contained
