"""Domain-model invariant tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.organizational_intelligence.enums import (
    ApprovalAuthorityKind,
    ApprovalDecision,
    CommunicationPatternKind,
    IntelligenceScope,
    MemoryArtifactKind,
    MemoryArtifactStatus,
    OperationalPatternKind,
    RecommendationKind,
    RecommendationStatus,
    RetrievalEligibility,
    SopFindingKind,
    SopFindingSeverity,
    SopStatus,
    TonalityClass,
    TonalityIntensity,
)
from app.organizational_intelligence.identity import (
    ApprovalId,
    ApprovedPatternId,
    CandidatePatternId,
    CommunicationPatternId,
    MemoryArtifactId,
    MemoryEvolutionProposalId,
    RecommendationId,
    SopAnalysisId,
    SopFindingId,
    SopId,
    SopVersionId,
)
from app.organizational_intelligence.lineage.tracker import (
    build_lineage_for_root,
    build_lineage_for_successor,
)
from app.organizational_intelligence.models.approval import (
    ApprovalRecord,
)
from app.organizational_intelligence.models.communication import (
    CommunicationPattern,
    CommunicationRetrievalCandidate,
)
from app.organizational_intelligence.models.memory import (
    ApprovedPattern,
    CandidatePattern,
    MemoryEvolutionProposal,
    OrganizationalMemoryArtifact,
)
from app.organizational_intelligence.models.pattern import (
    OperationalPatternAnalysis,
    OperationalPatternObservation,
)
from app.organizational_intelligence.models.recommendation import (
    OrganizationalRecommendation,
    RecommendationRationale,
)
from app.organizational_intelligence.models.sop import (
    SopAnalysis,
    SopFinding,
    SopVersion,
    StandardOperatingProcedure,
)
from app.organizational_intelligence.models.tonality import (
    TonalityAnalysis,
    TonalityTag,
)


_NOW = datetime.now(tz=timezone.utc)


def _sop_version(sop_id: SopId, version: int = 1) -> SopVersion:
    return SopVersion(
        version_id=SopVersionId(uuid.uuid4()),
        sop_id=sop_id,
        version=version,
        title="t",
        body="b",
        content_fingerprint="fp",
        ingested_at=_NOW,
    )


def test_sop_version_rejects_naive_datetime() -> None:
    sid = SopId(uuid.uuid4())
    with pytest.raises(ValueError):
        SopVersion(
            version_id=SopVersionId(uuid.uuid4()),
            sop_id=sid,
            version=1,
            title="t",
            body="b",
            content_fingerprint="fp",
            ingested_at=datetime(2026, 1, 1),
        )


def test_sop_version_rejects_zero_version() -> None:
    sid = SopId(uuid.uuid4())
    with pytest.raises(ValueError):
        SopVersion(
            version_id=SopVersionId(uuid.uuid4()),
            sop_id=sid,
            version=0,
            title="t",
            body="b",
            content_fingerprint="fp",
            ingested_at=_NOW,
        )


def test_standard_operating_procedure_validates() -> None:
    sid = SopId(uuid.uuid4())
    sop = StandardOperatingProcedure(
        sop_id=sid,
        tenant_id="t",
        scope=IntelligenceScope.TENANT,
        external_handle="h",
        status=SopStatus.INGESTED,
        current_version=_sop_version(sid),
        ingested_at=_NOW,
        last_updated_at=_NOW,
    )
    assert sop.revision == 0
    assert sop.scope is IntelligenceScope.TENANT


def test_sop_version_mismatch_rejected() -> None:
    sid = SopId(uuid.uuid4())
    other = SopId(uuid.uuid4())
    bad_version = _sop_version(other)
    with pytest.raises(ValueError):
        StandardOperatingProcedure(
            sop_id=sid,
            tenant_id=None,
            scope=IntelligenceScope.TENANT,
            external_handle="h",
            status=SopStatus.INGESTED,
            current_version=bad_version,
            ingested_at=_NOW,
            last_updated_at=_NOW,
        )


def test_sop_finding_rejects_negative_ordinal() -> None:
    sid = SopId(uuid.uuid4())
    with pytest.raises(ValueError):
        SopFinding(
            finding_id=SopFindingId(uuid.uuid4()),
            sop_id=sid,
            sop_version=1,
            ordinal=-1,
            kind=SopFindingKind.AMBIGUITY,
            severity=SopFindingSeverity.LOW,
            summary="x",
        )


def test_sop_analysis_validates() -> None:
    sid = SopId(uuid.uuid4())
    a = SopAnalysis(
        analysis_id=SopAnalysisId(uuid.uuid4()),
        sop_id=sid,
        sop_version=1,
        findings=(),
        analyzed_at=_NOW,
        analyzer_signature="sig.v1",
    )
    assert a.findings == ()


def test_tonality_tag_confidence_bounds() -> None:
    with pytest.raises(ValueError):
        TonalityTag(
            tonality_class=TonalityClass.CALM,
            intensity=TonalityIntensity.LOW,
            confidence=1.5,
        )


def test_tonality_analysis_primary_must_be_in_tags() -> None:
    primary = TonalityTag(
        tonality_class=TonalityClass.CALM,
        intensity=TonalityIntensity.LOW,
        confidence=0.5,
    )
    other = TonalityTag(
        tonality_class=TonalityClass.NEUTRAL,
        intensity=TonalityIntensity.LOW,
        confidence=0.4,
    )
    with pytest.raises(ValueError):
        TonalityAnalysis(
            analysis_id=uuid.uuid4(),
            content_fingerprint="fp",
            tags=(other,),
            primary_tag=primary,
            analyzed_at=_NOW,
            analyzer_signature="sig",
        )


def test_communication_pattern_requires_classes() -> None:
    with pytest.raises(ValueError):
        CommunicationPattern(
            pattern_id=CommunicationPatternId(uuid.uuid4()),
            tenant_id=None,
            scope=IntelligenceScope.TENANT,
            kind=CommunicationPatternKind.EMPATHY,
            handle="h",
            body="b",
            applicable_classes=(),
            approval_id=ApprovalId(uuid.uuid4()),
            registered_at=_NOW,
        )


def test_communication_retrieval_candidate_score_bounds() -> None:
    pattern = CommunicationPattern(
        pattern_id=CommunicationPatternId(uuid.uuid4()),
        tenant_id=None,
        scope=IntelligenceScope.TENANT,
        kind=CommunicationPatternKind.EMPATHY,
        handle="h",
        body="b",
        applicable_classes=(TonalityClass.NEUTRAL,),
        approval_id=ApprovalId(uuid.uuid4()),
        registered_at=_NOW,
    )
    with pytest.raises(ValueError):
        CommunicationRetrievalCandidate(
            pattern=pattern, score=1.1, match_reason="r"
        )


def test_pattern_lineage_rejects_cycle() -> None:
    a = MemoryArtifactId(uuid.uuid4())
    b = MemoryArtifactId(uuid.uuid4())
    root = build_lineage_for_root(artifact_id=a)
    succ = build_lineage_for_successor(
        artifact_id=b, parent_lineage=root
    )
    assert succ.depth == 1
    assert succ.root_artifact_id == a
    with pytest.raises(Exception):
        build_lineage_for_successor(
            artifact_id=a, parent_lineage=succ
        )


def test_organizational_memory_artifact_eligibility_invariant() -> None:
    art_id = MemoryArtifactId(uuid.uuid4())
    lineage = build_lineage_for_root(artifact_id=art_id)
    with pytest.raises(ValueError):
        OrganizationalMemoryArtifact(
            artifact_id=art_id,
            kind=MemoryArtifactKind.COMMUNICATION_PATTERN,
            scope=IntelligenceScope.TENANT,
            tenant_id=None,
            status=MemoryArtifactStatus.UNDER_REVIEW,
            body="b",
            content_fingerprint="fp",
            candidate_id=None,
            approved_pattern_id=None,
            approval_id=None,
            proposal_id=None,
            lineage=lineage,
            eligibility=RetrievalEligibility.ELIGIBLE,
            created_at=_NOW,
            updated_at=_NOW,
        )


def test_organizational_memory_artifact_approved_requires_approval() -> None:
    art_id = MemoryArtifactId(uuid.uuid4())
    lineage = build_lineage_for_root(artifact_id=art_id)
    with pytest.raises(ValueError):
        OrganizationalMemoryArtifact(
            artifact_id=art_id,
            kind=MemoryArtifactKind.COMMUNICATION_PATTERN,
            scope=IntelligenceScope.TENANT,
            tenant_id=None,
            status=MemoryArtifactStatus.APPROVED,
            body="b",
            content_fingerprint="fp",
            candidate_id=None,
            approved_pattern_id=None,
            approval_id=None,
            proposal_id=None,
            lineage=lineage,
            eligibility=RetrievalEligibility.ELIGIBLE,
            created_at=_NOW,
            updated_at=_NOW,
        )


def test_approval_record_human_authority_requires_handle() -> None:
    with pytest.raises(ValueError):
        ApprovalRecord(
            approval_id=ApprovalId(uuid.uuid4()),
            target_id=uuid.uuid4(),
            target_kind="x",
            decision=ApprovalDecision.APPROVED,
            authority=ApprovalAuthorityKind.HUMAN_OPERATOR,
            approver_handle="",
            decided_at=_NOW,
        )


def test_recommendation_terminal_status_requires_approval() -> None:
    with pytest.raises(ValueError):
        OrganizationalRecommendation(
            recommendation_id=RecommendationId(uuid.uuid4()),
            kind=RecommendationKind.SOP_OPTIMIZATION,
            scope=IntelligenceScope.TENANT,
            tenant_id=None,
            status=RecommendationStatus.APPROVED,
            title="t",
            body="b",
            rationale=RecommendationRationale(summary="s"),
            target_handle="x",
            proposed_at=_NOW,
        )


def test_pattern_observation_validates_counts() -> None:
    with pytest.raises(ValueError):
        OperationalPatternObservation(
            observation_id=uuid.uuid4(),
            seed="s",
            kind=OperationalPatternKind.OPERATIONAL_DRIFT,
            summary="x",
            occurrence_count=0,
            first_seen_at=_NOW,
            last_seen_at=_NOW,
        )


def test_operational_pattern_analysis_validates() -> None:
    a = OperationalPatternAnalysis(
        analysis_id=uuid.uuid4(),
        seed="s",
        analyzed_at=_NOW,
        analyzer_signature="sig",
        observations=(),
    )
    assert a.observations == ()


def test_candidate_pattern_validates() -> None:
    c = CandidatePattern(
        candidate_id=CandidatePatternId(uuid.uuid4()),
        observation_seed="s",
        kind=MemoryArtifactKind.OPERATIONAL_OBSERVATION,
        summary="sum",
        body="body",
        content_fingerprint="fp",
        evidence=(),
        extracted_at=_NOW,
        extractor_signature="sig.v1",
    )
    assert c.scope is IntelligenceScope.TENANT


def test_approved_pattern_validates() -> None:
    p = ApprovedPattern(
        approved_pattern_id=ApprovedPatternId(uuid.uuid4()),
        candidate_id=CandidatePatternId(uuid.uuid4()),
        approval_id=ApprovalId(uuid.uuid4()),
        approved_at=_NOW,
        body="b",
        kind=MemoryArtifactKind.COMMUNICATION_PATTERN,
        scope=IntelligenceScope.TENANT,
    )
    assert p.body == "b"


def test_memory_evolution_proposal_status_default() -> None:
    p = MemoryEvolutionProposal(
        proposal_id=MemoryEvolutionProposalId(uuid.uuid4()),
        candidate_id=CandidatePatternId(uuid.uuid4()),
        proposed_at=_NOW,
        rationale="r",
        evidence_summary=(),
    )
    assert p.status is MemoryArtifactStatus.CANDIDATE
