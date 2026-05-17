"""End-to-end tests for the organizational-intelligence runtime."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.organizational_intelligence import (
    AnalyzeOperationalPatternsRequest,
    AnalyzeSopRequest,
    ApprovalAuthorityKind,
    ApprovalDecision,
    ApprovalRecord,
    ApprovePatternRequest,
    ApproveRecommendationRequest,
    ClassifyTonalityRequest,
    CommunicationPatternKind,
    GenerateRecommendationRequest,
    InMemoryIntelligencePersistence,
    IngestSopRequest,
    IntelligenceApprovalError,
    IntelligenceAuthorityError,
    IntelligenceScope,
    ListMemoryArtifactsRequest,
    MemoryArtifactKind,
    MemoryArtifactStatus,
    MemoryEvolutionProposalRequest,
    OperationalPatternKind,
    OperationalPatternObservation,
    OrganizationalIntelligenceRuntime,
    RecommendationKind,
    RecommendationRationale,
    RecommendationStatus,
    RegisterCommunicationPatternRequest,
    RejectPatternRequest,
    RetireMemoryArtifactRequest,
    RetrievalEligibility,
    RetrieveCommunicationPatternsRequest,
    SupersedeMemoryArtifactRequest,
    TonalityClass,
)
from app.organizational_intelligence.identity import (
    derive_approval_id,
    derive_operational_pattern_observation_id,
)


# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def runtime() -> OrganizationalIntelligenceRuntime:
    return OrganizationalIntelligenceRuntime(
        persistence=InMemoryIntelligencePersistence()
    )


def _approval(
    *,
    target_id: uuid.UUID,
    target_kind: str,
    decision: ApprovalDecision = ApprovalDecision.APPROVED,
    authority: ApprovalAuthorityKind = (
        ApprovalAuthorityKind.HUMAN_OPERATOR
    ),
    handle: str = "alice",
) -> ApprovalRecord:
    decided_at = datetime.now(tz=timezone.utc)
    return ApprovalRecord(
        approval_id=derive_approval_id(
            target_id=target_id,
            decision=decision.value,
            approver_handle=handle,
            decided_at_iso=decided_at.isoformat(),
        ),
        target_id=target_id,
        target_kind=target_kind,
        decision=decision,
        authority=authority,
        approver_handle=handle,
        decided_at=decided_at,
    )


# ─── SOP runtime ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sop_ingest_then_analyze(runtime) -> None:
    env = await runtime.sop.ingest_sop(
        IngestSopRequest(
            external_handle="sop-1",
            title="Onboarding",
            body=(
                "Greet customer maybe. Manager pending. tbd. "
                "Always but never escalate."
            ),
            tenant_id="t1",
        )
    )
    assert env.is_ok, (env.error, env.trace.error)
    sop = env.result.sop
    assert sop.status.value == "ingested"
    assert sop.current_version.version == 1

    env2 = await runtime.sop.analyze_sop(
        AnalyzeSopRequest(sop_id=sop.sop_id)
    )
    assert env2.is_ok, (env2.error, env2.trace.error)
    findings = env2.result.analysis.findings
    assert len(findings) >= 3
    kinds = {f.kind.value for f in findings}
    assert {"ambiguity", "contradiction", "missing_authority"} <= kinds
    assert env2.result.sop.status.value == "analyzed"
    assert env2.result.sop.revision == 2


@pytest.mark.asyncio
async def test_sop_reingest_increments_version(runtime) -> None:
    e1 = await runtime.sop.ingest_sop(
        IngestSopRequest(
            external_handle="sop-x",
            title="x",
            body="b",
            tenant_id=None,
        )
    )
    assert e1.is_ok
    v1 = e1.result.sop.current_version.version
    e2 = await runtime.sop.ingest_sop(
        IngestSopRequest(
            external_handle="sop-x",
            title="x",
            body="b2",
            tenant_id=None,
        )
    )
    assert e2.is_ok
    assert e2.result.sop.current_version.version == v1 + 1
    assert e2.result.sop.version_history[-1] == (
        e1.result.sop.current_version.version_id
    )


@pytest.mark.asyncio
async def test_sop_analyze_unknown_returns_error(runtime) -> None:
    env = await runtime.sop.analyze_sop(
        AnalyzeSopRequest(sop_id=uuid.uuid4())
    )
    assert not env.is_ok
    assert env.error is not None


# ─── Tonality runtime ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tonality_classify_deterministic(runtime) -> None:
    e1 = await runtime.tonality.classify(
        ClassifyTonalityRequest(
            content="I am furious manager now",
            tenant_id="t",
        )
    )
    assert e1.is_ok
    p1 = e1.result.analysis.primary_tag
    assert p1.tonality_class is TonalityClass.ESCALATED

    e2 = await runtime.tonality.classify(
        ClassifyTonalityRequest(
            content="I am furious manager now",
            tenant_id="t",
        )
    )
    assert e2.is_ok
    assert (
        e1.result.analysis.analysis_id
        == e2.result.analysis.analysis_id
    )


@pytest.mark.asyncio
async def test_tonality_neutral_when_no_markers(runtime) -> None:
    env = await runtime.tonality.classify(
        ClassifyTonalityRequest(
            content="abcdefghi nothing notable",
            tenant_id="t",
        )
    )
    assert env.is_ok
    assert (
        env.result.analysis.primary_tag.tonality_class
        is TonalityClass.NEUTRAL
    )


# ─── Communication runtime ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_communication_register_requires_approved_decision(
    runtime,
) -> None:
    bad = _approval(
        target_id=uuid.uuid4(),
        target_kind="communication_pattern",
        decision=ApprovalDecision.DEFERRED,
    )
    env = await runtime.communication.register_pattern(
        RegisterCommunicationPatternRequest(
            handle="h",
            body="b",
            kind=CommunicationPatternKind.EMPATHY,
            applicable_classes=(TonalityClass.FRUSTRATED,),
            approval=bad,
            tenant_id="t",
        )
    )
    assert not env.is_ok
    assert isinstance(env.error, IntelligenceApprovalError)


@pytest.mark.asyncio
async def test_communication_register_rejects_system_authority(
    runtime,
) -> None:
    bad = _approval(
        target_id=uuid.uuid4(),
        target_kind="communication_pattern",
        authority=ApprovalAuthorityKind.SYSTEM,
    )
    env = await runtime.communication.register_pattern(
        RegisterCommunicationPatternRequest(
            handle="h",
            body="b",
            kind=CommunicationPatternKind.EMPATHY,
            applicable_classes=(TonalityClass.FRUSTRATED,),
            approval=bad,
            tenant_id="t",
        )
    )
    assert not env.is_ok
    assert isinstance(env.error, IntelligenceAuthorityError)


@pytest.mark.asyncio
async def test_communication_retrieve_returns_only_matching(
    runtime,
) -> None:
    a1 = _approval(
        target_id=uuid.uuid4(),
        target_kind="communication_pattern",
    )
    await runtime.communication.register_pattern(
        RegisterCommunicationPatternRequest(
            handle="empathy.v1",
            body="I understand.",
            kind=CommunicationPatternKind.EMPATHY,
            applicable_classes=(TonalityClass.FRUSTRATED,),
            approval=a1,
            tenant_id="t",
        )
    )
    a2 = _approval(
        target_id=uuid.uuid4(),
        target_kind="communication_pattern",
    )
    await runtime.communication.register_pattern(
        RegisterCommunicationPatternRequest(
            handle="closure.v1",
            body="Glad we resolved this.",
            kind=CommunicationPatternKind.CLOSURE,
            applicable_classes=(TonalityClass.POSITIVE,),
            approval=a2,
            tenant_id="t",
        )
    )
    env = await runtime.communication.retrieve_patterns(
        RetrieveCommunicationPatternsRequest(
            primary_class=TonalityClass.FRUSTRATED,
            tenant_id="t",
            limit=10,
        )
    )
    assert env.is_ok
    handles = [c.pattern.handle for c in env.result.candidates]
    assert handles == ["empathy.v1"]


# ─── Memory evolution runtime ────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_propose_creates_under_review_artifact(
    runtime,
) -> None:
    env = await runtime.memory.propose(
        MemoryEvolutionProposalRequest(
            observation_seed="obs|1",
            summary="s",
            body="b",
            kind=MemoryArtifactKind.OPERATIONAL_OBSERVATION,
            evidence=("session-1",),
            tenant_id="t",
        )
    )
    assert env.is_ok
    art = env.result.artifact
    assert art.status is MemoryArtifactStatus.UNDER_REVIEW
    assert art.eligibility is RetrievalEligibility.PENDING
    assert art.candidate_id == env.result.candidate.candidate_id


@pytest.mark.asyncio
async def test_memory_propose_idempotent(runtime) -> None:
    e1 = await runtime.memory.propose(
        MemoryEvolutionProposalRequest(
            observation_seed="obs|x",
            summary="s",
            body="b",
            kind=MemoryArtifactKind.OPERATIONAL_OBSERVATION,
            tenant_id="t",
        )
    )
    e2 = await runtime.memory.propose(
        MemoryEvolutionProposalRequest(
            observation_seed="obs|x",
            summary="s",
            body="b",
            kind=MemoryArtifactKind.OPERATIONAL_OBSERVATION,
            tenant_id="t",
        )
    )
    assert e1.is_ok and e2.is_ok
    assert (
        e1.result.artifact.artifact_id
        == e2.result.artifact.artifact_id
    )
    assert e2.result.artifact.revision == 1


@pytest.mark.asyncio
async def test_memory_approve_requires_human_authority(
    runtime,
) -> None:
    e_propose = await runtime.memory.propose(
        MemoryEvolutionProposalRequest(
            observation_seed="obs|need-human",
            summary="s",
            body="b",
            kind=MemoryArtifactKind.OPERATIONAL_OBSERVATION,
        )
    )
    candidate = e_propose.result.candidate

    bad = _approval(
        target_id=candidate.candidate_id,
        target_kind="candidate_pattern",
        authority=ApprovalAuthorityKind.SYSTEM,
    )
    env = await runtime.memory.approve(
        ApprovePatternRequest(
            candidate_id=candidate.candidate_id,
            approval=bad,
        )
    )
    assert not env.is_ok
    assert isinstance(env.error, IntelligenceAuthorityError)


@pytest.mark.asyncio
async def test_memory_approve_lifts_to_eligible(runtime) -> None:
    e_propose = await runtime.memory.propose(
        MemoryEvolutionProposalRequest(
            observation_seed="obs|approve",
            summary="s",
            body="b",
            kind=MemoryArtifactKind.OPERATIONAL_OBSERVATION,
        )
    )
    candidate = e_propose.result.candidate
    a = _approval(
        target_id=candidate.candidate_id,
        target_kind="candidate_pattern",
    )
    env = await runtime.memory.approve(
        ApprovePatternRequest(
            candidate_id=candidate.candidate_id, approval=a
        )
    )
    assert env.is_ok, (env.error, env.trace.error)
    assert (
        env.result.artifact.status
        is MemoryArtifactStatus.APPROVED
    )
    assert (
        env.result.artifact.eligibility
        is RetrievalEligibility.ELIGIBLE
    )
    assert env.result.approved_pattern is not None


@pytest.mark.asyncio
async def test_memory_approve_twice_rejects(runtime) -> None:
    e_propose = await runtime.memory.propose(
        MemoryEvolutionProposalRequest(
            observation_seed="obs|twice",
            summary="s",
            body="b",
            kind=MemoryArtifactKind.OPERATIONAL_OBSERVATION,
        )
    )
    candidate = e_propose.result.candidate
    a1 = _approval(
        target_id=candidate.candidate_id,
        target_kind="candidate_pattern",
    )
    await runtime.memory.approve(
        ApprovePatternRequest(
            candidate_id=candidate.candidate_id, approval=a1
        )
    )
    a2 = _approval(
        target_id=candidate.candidate_id,
        target_kind="candidate_pattern",
        handle="bob",
    )
    env = await runtime.memory.approve(
        ApprovePatternRequest(
            candidate_id=candidate.candidate_id, approval=a2
        )
    )
    assert not env.is_ok
    assert isinstance(env.error, IntelligenceApprovalError)


@pytest.mark.asyncio
async def test_memory_reject_marks_ineligible(runtime) -> None:
    e_propose = await runtime.memory.propose(
        MemoryEvolutionProposalRequest(
            observation_seed="obs|reject",
            summary="s",
            body="b",
            kind=MemoryArtifactKind.OPERATIONAL_OBSERVATION,
        )
    )
    candidate = e_propose.result.candidate
    rej = _approval(
        target_id=candidate.candidate_id,
        target_kind="candidate_pattern",
        decision=ApprovalDecision.REJECTED,
    )
    env = await runtime.memory.reject(
        RejectPatternRequest(
            candidate_id=candidate.candidate_id, approval=rej
        )
    )
    assert env.is_ok
    art = env.result.artifact
    assert art.status is MemoryArtifactStatus.REJECTED
    assert art.eligibility is RetrievalEligibility.INELIGIBLE


@pytest.mark.asyncio
async def test_memory_supersede_chains_lineage(runtime) -> None:
    # propose+approve A
    eA = await runtime.memory.propose(
        MemoryEvolutionProposalRequest(
            observation_seed="obs|A",
            summary="s",
            body="bA",
            kind=MemoryArtifactKind.OPERATIONAL_OBSERVATION,
        )
    )
    cA = eA.result.candidate
    aA = _approval(
        target_id=cA.candidate_id,
        target_kind="candidate_pattern",
    )
    rA = await runtime.memory.approve(
        ApprovePatternRequest(
            candidate_id=cA.candidate_id, approval=aA
        )
    )
    A = rA.result.artifact

    # propose+approve B
    eB = await runtime.memory.propose(
        MemoryEvolutionProposalRequest(
            observation_seed="obs|B",
            summary="s",
            body="bB",
            kind=MemoryArtifactKind.OPERATIONAL_OBSERVATION,
        )
    )
    cB = eB.result.candidate
    aB = _approval(
        target_id=cB.candidate_id,
        target_kind="candidate_pattern",
    )
    rB = await runtime.memory.approve(
        ApprovePatternRequest(
            candidate_id=cB.candidate_id, approval=aB
        )
    )
    B = rB.result.artifact

    a_super = _approval(
        target_id=A.artifact_id,
        target_kind="memory_artifact",
    )
    env = await runtime.memory.supersede(
        SupersedeMemoryArtifactRequest(
            predecessor_id=A.artifact_id,
            successor_id=B.artifact_id,
            approval=a_super,
        )
    )
    assert env.is_ok, (env.error, env.trace.error)
    assert (
        env.result.predecessor.status
        is MemoryArtifactStatus.SUPERSEDED
    )
    assert env.result.predecessor.superseded_by == B.artifact_id
    assert env.result.successor.lineage.depth == 1
    assert env.result.successor.lineage.parent_artifact_id == (
        A.artifact_id
    )


@pytest.mark.asyncio
async def test_memory_retire_only_approved(runtime) -> None:
    e_propose = await runtime.memory.propose(
        MemoryEvolutionProposalRequest(
            observation_seed="obs|retire",
            summary="s",
            body="b",
            kind=MemoryArtifactKind.OPERATIONAL_OBSERVATION,
        )
    )
    art = e_propose.result.artifact
    a = _approval(
        target_id=art.artifact_id,
        target_kind="memory_artifact",
    )
    env = await runtime.memory.retire(
        RetireMemoryArtifactRequest(
            artifact_id=art.artifact_id, approval=a
        )
    )
    assert not env.is_ok
    assert isinstance(env.error, IntelligenceApprovalError)


@pytest.mark.asyncio
async def test_memory_list_filters_eligible(runtime) -> None:
    # create 1 approved, 1 candidate
    e_propose = await runtime.memory.propose(
        MemoryEvolutionProposalRequest(
            observation_seed="obs|listed",
            summary="s",
            body="b",
            kind=MemoryArtifactKind.OPERATIONAL_OBSERVATION,
        )
    )
    candidate = e_propose.result.candidate
    a = _approval(
        target_id=candidate.candidate_id,
        target_kind="candidate_pattern",
    )
    await runtime.memory.approve(
        ApprovePatternRequest(
            candidate_id=candidate.candidate_id, approval=a
        )
    )
    await runtime.memory.propose(
        MemoryEvolutionProposalRequest(
            observation_seed="obs|listed-2",
            summary="s",
            body="b2",
            kind=MemoryArtifactKind.OPERATIONAL_OBSERVATION,
        )
    )

    env = await runtime.memory.list_artifacts(
        ListMemoryArtifactsRequest(eligible_only=True)
    )
    assert env.is_ok
    eligible_ids = {a.artifact_id for a in env.result.artifacts}
    assert all(
        a.eligibility is RetrievalEligibility.ELIGIBLE
        for a in env.result.artifacts
    )
    assert len(eligible_ids) == 1


# ─── Pattern analysis ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_operational_pattern_analyze_orders_observations(
    runtime,
) -> None:
    now = datetime.now(tz=timezone.utc)
    obs_low = OperationalPatternObservation(
        observation_id=derive_operational_pattern_observation_id(
            seed="ops|low"
        ),
        seed="ops|low",
        kind=OperationalPatternKind.OPERATIONAL_DRIFT,
        summary="s",
        occurrence_count=2,
        first_seen_at=now,
        last_seen_at=now,
    )
    obs_high = OperationalPatternObservation(
        observation_id=derive_operational_pattern_observation_id(
            seed="ops|high"
        ),
        seed="ops|high",
        kind=OperationalPatternKind.ESCALATION_FAILURE,
        summary="s",
        occurrence_count=10,
        first_seen_at=now,
        last_seen_at=now,
    )
    env = await runtime.patterns.analyze(
        AnalyzeOperationalPatternsRequest(
            seed="batch|1",
            observations=(obs_low, obs_high),
        )
    )
    assert env.is_ok
    sorted_kinds = [
        o.kind.value for o in env.result.analysis.observations
    ]
    assert sorted_kinds == sorted(sorted_kinds)


# ─── Recommendation runtime ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_recommendation_starts_proposed(runtime) -> None:
    env = await runtime.recommendations.generate(
        GenerateRecommendationRequest(
            title="t",
            body="b",
            kind=RecommendationKind.SOP_OPTIMIZATION,
            target_handle="x",
            rationale=RecommendationRationale(summary="r"),
            tenant_id="t1",
            scope=IntelligenceScope.TENANT,
        )
    )
    assert env.is_ok
    assert (
        env.result.recommendation.status
        is RecommendationStatus.PROPOSED
    )


@pytest.mark.asyncio
async def test_recommendation_review_decisions_map_correctly(
    runtime,
) -> None:
    for decision, expected_status in (
        (
            ApprovalDecision.APPROVED,
            RecommendationStatus.APPROVED,
        ),
        (
            ApprovalDecision.REJECTED,
            RecommendationStatus.REJECTED,
        ),
        (
            ApprovalDecision.DEFERRED,
            RecommendationStatus.DEFERRED,
        ),
    ):
        env = await runtime.recommendations.generate(
            GenerateRecommendationRequest(
                title=f"t-{decision.value}",
                body=f"b-{decision.value}",
                kind=RecommendationKind.PATTERN_ADOPTION,
                target_handle="x",
                rationale=RecommendationRationale(summary="r"),
                tenant_id="t1",
            )
        )
        rec = env.result.recommendation
        a = _approval(
            target_id=rec.recommendation_id,
            target_kind="recommendation",
            decision=decision,
        )
        review = await runtime.recommendations.record_review(
            ApproveRecommendationRequest(
                recommendation_id=rec.recommendation_id,
                approval=a,
            )
        )
        assert review.is_ok
        assert (
            review.result.recommendation.status
            is expected_status
        )
