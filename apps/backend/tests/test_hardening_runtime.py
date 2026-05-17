"""End-to-end tests for the `HardeningRuntime`."""

from __future__ import annotations

import pytest

from app.hardening import (
    AuditDependenciesRequest,
    ClassifyContainmentRequest,
    ContainmentClassification,
    DetectContaminationRequest,
    FailureClassification,
    HardeningRuntime,
    HardeningSeverity,
    InMemoryHardeningPersistence,
    IntegrityStatus,
    RecordFailureRequest,
    ReplayStatus,
    SubstrateName,
    SurvivabilityStatus,
    ValidateAuthorityOwnershipRequest,
    ValidateLineageRequest,
    ValidateOrderingRequest,
    ValidateReconstructionRequest,
    ValidateReplayRequest,
    ValidateSurvivabilityRequest,
)


@pytest.fixture()
def runtime() -> HardeningRuntime:
    return HardeningRuntime(
        persistence=InMemoryHardeningPersistence()
    )


@pytest.mark.asyncio
async def test_validate_authority_ownership_persists_audit(
    runtime: HardeningRuntime,
) -> None:
    env = await runtime.validate_authority_ownership(
        ValidateAuthorityOwnershipRequest(
            observed_owners={
                "operational_restrictions": (
                    SubstrateName.AGENTS,
                )
            },
            correlation_id="corr-1",
            request_id="req-1",
        )
    )
    assert env.is_ok
    assert env.result.containment is not None
    assert len(env.result.violations) == 1
    audits = await runtime.persistence.list_audits()
    assert len(audits) == 1


@pytest.mark.asyncio
async def test_validate_lineage_passes(
    runtime: HardeningRuntime,
) -> None:
    env = await runtime.validate_lineage(
        ValidateLineageRequest(
            records=(("root", None), ("child", "root")),
            scope="unit",
        )
    )
    assert env.is_ok
    assert env.result.integrity_status is IntegrityStatus.PASSED


@pytest.mark.asyncio
async def test_validate_replay_byte_identical(
    runtime: HardeningRuntime,
) -> None:
    env = await runtime.validate_replay_equivalence(
        ValidateReplayRequest(
            canonical_payload={"a": 1, "b": [1, 2]},
            candidate_payload={"b": [1, 2], "a": 1},
        )
    )
    assert env.is_ok
    assert env.result.finding.is_byte_identical


@pytest.mark.asyncio
async def test_validate_reconstruction_drift_recorded(
    runtime: HardeningRuntime,
) -> None:
    env = await runtime.validate_reconstruction(
        ValidateReconstructionRequest(
            original_payload={"x": 1},
            reconstructed_payload={"x": 2},
        )
    )
    assert env.is_ok
    assert env.result.finding.status is ReplayStatus.DRIFTED


@pytest.mark.asyncio
async def test_validate_ordering(
    runtime: HardeningRuntime,
) -> None:
    env_pass = await runtime.validate_ordering(
        ValidateOrderingRequest(
            items=("a", "b", "c"),
            key_fn=lambda x: x,
        )
    )
    env_fail = await runtime.validate_ordering(
        ValidateOrderingRequest(
            items=("b", "a", "c"),
            key_fn=lambda x: x,
        )
    )
    assert (
        env_pass.result.integrity_status
        is IntegrityStatus.PASSED
    )
    assert (
        env_fail.result.integrity_status
        is IntegrityStatus.FAILED
    )


@pytest.mark.asyncio
async def test_detect_contamination_with_injected_source(
    runtime: HardeningRuntime,
) -> None:
    env = await runtime.detect_contamination(
        DetectContaminationRequest(
            substrate=SubstrateName.SUPERVISOR,
            substrate_path="/nonexistent",
            forbidden_module_prefixes=("app.governance",),
            metadata={
                "source_lines_by_path": {
                    "x.py": "from app.governance import g\n",
                },
            },
        )
    )
    assert env.is_ok
    assert (
        env.result.integrity_status is IntegrityStatus.FAILED
    )


@pytest.mark.asyncio
async def test_audit_dependencies(
    runtime: HardeningRuntime,
) -> None:
    env = await runtime.audit_dependencies(
        AuditDependenciesRequest(
            substrate_paths=(
                (SubstrateName.AGENTS, "/agents"),
            ),
            forbidden_edges=(
                (
                    SubstrateName.AGENTS,
                    SubstrateName.GOVERNANCE,
                ),
            ),
            metadata={
                "source_lines_by_substrate": {
                    SubstrateName.AGENTS: {
                        "x.py": "from app.governance import G\n",
                    },
                },
            },
        )
    )
    assert env.is_ok
    assert env.result.finding.forbidden_edges
    assert (
        env.result.finding.forbidden_edges[0].source
        == SubstrateName.AGENTS
    )


@pytest.mark.asyncio
async def test_validate_survivability(
    runtime: HardeningRuntime,
) -> None:
    env = await runtime.validate_survivability(
        ValidateSurvivabilityRequest(
            expected_count=10,
            survived_count=10,
            scope="memory",
        )
    )
    assert (
        env.result.survivability_status
        is SurvivabilityStatus.SURVIVED
    )


@pytest.mark.asyncio
async def test_record_failure_persists_record(
    runtime: HardeningRuntime,
) -> None:
    env = await runtime.record_failure(
        RecordFailureRequest(
            substrate=SubstrateName.GOVERNANCE,
            classification=FailureClassification.SUBSTRATE_LOCAL,
            containment=ContainmentClassification.CONTAINED,
            severity=HardeningSeverity.MEDIUM,
            summary="bounded",
            error_class_name="ValueError",
            seed="failure-1",
        )
    )
    assert env.is_ok
    records = await runtime.persistence.list_failure_records()
    assert len(records) == 1


@pytest.mark.asyncio
async def test_classify_containment(
    runtime: HardeningRuntime,
) -> None:
    env = await runtime.classify_containment(
        ClassifyContainmentRequest(
            originating_substrate=SubstrateName.GOVERNANCE,
            observers=(
                SubstrateName.GOVERNANCE,
                SubstrateName.AGENTS,
            ),
        )
    )
    assert (
        env.result.classification
        is ContainmentClassification.LEAKED
    )


@pytest.mark.asyncio
async def test_runtime_is_never_raising_on_validation_errors(
    runtime: HardeningRuntime,
) -> None:
    env = await runtime.record_failure(
        RecordFailureRequest(
            substrate=SubstrateName.GOVERNANCE,
            classification=FailureClassification.SUBSTRATE_LOCAL,
            containment=ContainmentClassification.CONTAINED,
            severity=HardeningSeverity.MEDIUM,
            summary="x",
            error_class_name="X",
            seed="",  # invalid
        )
    )
    assert env.error is not None
    assert env.result is None
