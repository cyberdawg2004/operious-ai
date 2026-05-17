"""In-memory persistence invariants for the intelligence substrate."""

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
    RecommendationKind,
    RecommendationStatus,
    RetrievalEligibility,
    SopStatus,
    TonalityClass,
)
from app.organizational_intelligence.exceptions import (
    IntelligencePersistenceError,
)
from app.organizational_intelligence.identity import (
    ApprovalId,
    ApprovedPatternId,
    CandidatePatternId,
    CommunicationPatternId,
    MemoryArtifactId,
    MemoryEvolutionProposalId,
    RecommendationId,
    SopId,
    SopVersionId,
)
from app.organizational_intelligence.lineage.tracker import (
    build_lineage_for_root,
)
from app.organizational_intelligence.models.approval import (
    ApprovalRecord,
)
from app.organizational_intelligence.models.communication import (
    CommunicationPattern,
)
from app.organizational_intelligence.models.memory import (
    ApprovedPattern,
    CandidatePattern,
    MemoryEvolutionProposal,
    OrganizationalMemoryArtifact,
)
from app.organizational_intelligence.models.recommendation import (
    OrganizationalRecommendation,
    RecommendationRationale,
)
from app.organizational_intelligence.models.sop import (
    SopVersion,
    StandardOperatingProcedure,
)
from app.organizational_intelligence.persistence import (
    InMemoryIntelligencePersistence,
    MemoryArtifactQuery,
)


_NOW = datetime.now(tz=timezone.utc)


def _sop_v1(sid: SopId) -> SopVersion:
    return SopVersion(
        version_id=SopVersionId(uuid.uuid4()),
        sop_id=sid,
        version=1,
        title="t",
        body="b",
        content_fingerprint="fp",
        ingested_at=_NOW,
    )


def _sop(sid: SopId, revision: int) -> StandardOperatingProcedure:
    return StandardOperatingProcedure(
        sop_id=sid,
        tenant_id=None,
        scope=IntelligenceScope.TENANT,
        external_handle="h",
        status=SopStatus.INGESTED,
        current_version=_sop_v1(sid),
        ingested_at=_NOW,
        last_updated_at=_NOW,
        revision=revision,
    )


@pytest.mark.asyncio
async def test_save_sop_revision_must_be_monotonic() -> None:
    p = InMemoryIntelligencePersistence()
    sid = SopId(uuid.uuid4())
    await p.save_sop(_sop(sid, revision=1))
    with pytest.raises(IntelligencePersistenceError):
        await p.save_sop(_sop(sid, revision=1))
    await p.save_sop(_sop(sid, revision=2))


@pytest.mark.asyncio
async def test_save_communication_pattern_write_once() -> None:
    p = InMemoryIntelligencePersistence()
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
    await p.save_communication_pattern(pattern)
    with pytest.raises(IntelligencePersistenceError):
        await p.save_communication_pattern(pattern)


@pytest.mark.asyncio
async def test_save_candidate_write_once() -> None:
    p = InMemoryIntelligencePersistence()
    cid = CandidatePatternId(uuid.uuid4())
    c = CandidatePattern(
        candidate_id=cid,
        observation_seed="s",
        kind=MemoryArtifactKind.OPERATIONAL_OBSERVATION,
        summary="x",
        body="b",
        content_fingerprint="fp",
        evidence=(),
        extracted_at=_NOW,
        extractor_signature="sig",
    )
    await p.save_candidate(c)
    with pytest.raises(IntelligencePersistenceError):
        await p.save_candidate(c)


@pytest.mark.asyncio
async def test_save_memory_artifact_revision_monotonic() -> None:
    p = InMemoryIntelligencePersistence()
    aid = MemoryArtifactId(uuid.uuid4())
    lineage = build_lineage_for_root(artifact_id=aid)
    a1 = OrganizationalMemoryArtifact(
        artifact_id=aid,
        kind=MemoryArtifactKind.OPERATIONAL_OBSERVATION,
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
        eligibility=RetrievalEligibility.PENDING,
        created_at=_NOW,
        updated_at=_NOW,
        revision=1,
    )
    await p.save_memory_artifact(a1)
    with pytest.raises(IntelligencePersistenceError):
        await p.save_memory_artifact(a1)


@pytest.mark.asyncio
async def test_save_approval_write_once() -> None:
    p = InMemoryIntelligencePersistence()
    a = ApprovalRecord(
        approval_id=ApprovalId(uuid.uuid4()),
        target_id=uuid.uuid4(),
        target_kind="x",
        decision=ApprovalDecision.APPROVED,
        authority=ApprovalAuthorityKind.HUMAN_OPERATOR,
        approver_handle="alice",
        decided_at=_NOW,
    )
    await p.save_approval(a)
    with pytest.raises(IntelligencePersistenceError):
        await p.save_approval(a)


@pytest.mark.asyncio
async def test_save_recommendation_revision_monotonic() -> None:
    p = InMemoryIntelligencePersistence()
    rid = RecommendationId(uuid.uuid4())
    r1 = OrganizationalRecommendation(
        recommendation_id=rid,
        kind=RecommendationKind.SOP_OPTIMIZATION,
        scope=IntelligenceScope.TENANT,
        tenant_id=None,
        status=RecommendationStatus.PROPOSED,
        title="t",
        body="b",
        rationale=RecommendationRationale(summary="r"),
        target_handle="x",
        proposed_at=_NOW,
        revision=1,
    )
    await p.save_recommendation(r1)
    with pytest.raises(IntelligencePersistenceError):
        await p.save_recommendation(r1)


@pytest.mark.asyncio
async def test_list_memory_artifacts_filters_and_paginates() -> None:
    p = InMemoryIntelligencePersistence()
    for i in range(5):
        aid = MemoryArtifactId(uuid.uuid4())
        await p.save_memory_artifact(
            OrganizationalMemoryArtifact(
                artifact_id=aid,
                kind=MemoryArtifactKind.OPERATIONAL_OBSERVATION,
                scope=IntelligenceScope.TENANT,
                tenant_id="t" + str(i % 2),
                status=MemoryArtifactStatus.UNDER_REVIEW,
                body=f"b{i}",
                content_fingerprint=f"fp{i}",
                candidate_id=None,
                approved_pattern_id=None,
                approval_id=None,
                proposal_id=None,
                lineage=build_lineage_for_root(artifact_id=aid),
                eligibility=RetrievalEligibility.PENDING,
                created_at=_NOW,
                updated_at=_NOW,
                revision=1,
            )
        )
    page = await p.list_memory_artifacts(
        MemoryArtifactQuery(tenant_id="t0", limit=10)
    )
    assert all(a.tenant_id == "t0" for a in page.artifacts)
    assert page.total == sum(
        1 for i in range(5) if i % 2 == 0
    )


# Re-exports referenced for type checking
ApprovedPatternId  # noqa: B018
MemoryEvolutionProposalId  # noqa: B018
ApprovedPattern  # noqa: B018
MemoryEvolutionProposal  # noqa: B018
