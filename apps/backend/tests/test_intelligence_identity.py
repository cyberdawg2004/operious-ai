"""Replay-safe deterministic-derivation invariants for intelligence ids."""

from __future__ import annotations

import uuid

import pytest

from app.organizational_intelligence.identity import (
    derive_approval_id,
    derive_approved_pattern_id,
    derive_candidate_pattern_id,
    derive_communication_pattern_id,
    derive_memory_artifact_id,
    derive_memory_evolution_proposal_id,
    derive_operational_pattern_analysis_id,
    derive_operational_pattern_observation_id,
    derive_pattern_lineage_id,
    derive_recommendation_id,
    derive_sop_analysis_id,
    derive_sop_finding_id,
    derive_sop_id,
    derive_sop_version_id,
    derive_tonality_analysis_id,
    derive_trace_id,
    generate_pattern_lineage_id,
    generate_sop_id,
)


def test_uuid4_generators_unique() -> None:
    a = generate_sop_id()
    b = generate_sop_id()
    assert a != b
    assert isinstance(a, uuid.UUID) and isinstance(b, uuid.UUID)


def test_sop_id_deterministic() -> None:
    a = derive_sop_id(tenant_id="t1", external_handle="sop-1")
    b = derive_sop_id(tenant_id="t1", external_handle="sop-1")
    c = derive_sop_id(tenant_id="t2", external_handle="sop-1")
    assert a == b
    assert a != c


def test_generate_pattern_lineage_id_is_deterministic_from_root_artifact() -> None:
    root = uuid.uuid4()
    other = uuid.uuid4()

    assert generate_pattern_lineage_id(
        root_artifact_id=root
    ) == derive_pattern_lineage_id(root_artifact_id=root)
    assert generate_pattern_lineage_id(
        root_artifact_id=root
    ) != generate_pattern_lineage_id(root_artifact_id=other)


def test_sop_id_rejects_empty_handle() -> None:
    with pytest.raises(ValueError):
        derive_sop_id(tenant_id="t1", external_handle="")


def test_sop_version_id_deterministic_and_validates() -> None:
    sop = derive_sop_id(tenant_id=None, external_handle="x")
    assert derive_sop_version_id(
        sop_id=sop, version=2
    ) == derive_sop_version_id(sop_id=sop, version=2)
    assert derive_sop_version_id(
        sop_id=sop, version=1
    ) != derive_sop_version_id(sop_id=sop, version=2)
    with pytest.raises(ValueError):
        derive_sop_version_id(sop_id=sop, version=0)


def test_finding_and_analysis_ids_distinct() -> None:
    sop = derive_sop_id(tenant_id="t", external_handle="s")
    finding = derive_sop_finding_id(
        sop_id=sop, version=1, ordinal=0
    )
    analysis = derive_sop_analysis_id(sop_id=sop, version=1)
    assert finding != analysis


def test_candidate_artifact_approval_chain_deterministic() -> None:
    candidate = derive_candidate_pattern_id(
        observation_seed="seed-A"
    )
    artifact = derive_memory_artifact_id(
        kind="communication_pattern",
        content_fingerprint="fingerprint-xyz",
    )
    approval = derive_approval_id(
        target_id=candidate,
        decision="approved",
        approver_handle="alice",
        decided_at_iso="2026-01-01T00:00:00+00:00",
    )
    approved = derive_approved_pattern_id(
        candidate_id=candidate, approval_id=approval
    )
    proposal = derive_memory_evolution_proposal_id(
        candidate_id=candidate
    )
    lineage = derive_pattern_lineage_id(
        root_artifact_id=artifact
    )
    same_again = (
        derive_candidate_pattern_id(observation_seed="seed-A"),
        derive_memory_artifact_id(
            kind="communication_pattern",
            content_fingerprint="fingerprint-xyz",
        ),
        derive_approval_id(
            target_id=candidate,
            decision="approved",
            approver_handle="alice",
            decided_at_iso="2026-01-01T00:00:00+00:00",
        ),
        derive_approved_pattern_id(
            candidate_id=candidate, approval_id=approval
        ),
        derive_memory_evolution_proposal_id(
            candidate_id=candidate
        ),
        derive_pattern_lineage_id(
            root_artifact_id=artifact
        ),
    )
    assert (
        candidate,
        artifact,
        approval,
        approved,
        proposal,
        lineage,
    ) == same_again


def test_namespaces_dont_collide() -> None:
    seed = "abc"
    seen = {
        derive_candidate_pattern_id(observation_seed=seed),
        derive_operational_pattern_observation_id(seed=seed),
        derive_operational_pattern_analysis_id(seed=seed),
        derive_trace_id(seed=seed),
    }
    assert len(seen) == 4


def test_recommendation_and_communication_distinct() -> None:
    rec = derive_recommendation_id(
        scope="tenant|t1", content_fingerprint="fp"
    )
    comm = derive_communication_pattern_id(
        tenant_id="t1", pattern_handle="h"
    )
    tonality = derive_tonality_analysis_id(
        content_fingerprint="fp", correlation=None
    )
    assert rec != comm != tonality
