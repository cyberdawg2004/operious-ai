"""Pure-helper tests: serialisers, eligibility, scoring, lineage, adaptation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.organizational_intelligence.adaptation import (
    is_active_adoption,
    is_adaptation_event,
)
from app.organizational_intelligence.correlation import (
    build_correlation_seed,
    canonicalize_correlation_handles,
)
from app.organizational_intelligence.enums import (
    ApprovalAuthorityKind,
    ApprovalDecision,
    CommunicationPatternKind,
    IntelligenceScope,
    IntelligenceTraceKind,
    MemoryArtifactStatus,
    SopFindingSeverity,
    TonalityClass,
)
from app.organizational_intelligence.exceptions import (
    IntelligenceApprovalError,
    IntelligenceAuthorityError,
)
from app.organizational_intelligence.approval_gates.approval_gate import (
    require_approval_for_promotion,
    require_approval_for_registration,
    require_approval_for_review,
    require_approval_for_supersession,
)
from app.organizational_intelligence.identity import (
    ApprovalId,
    CommunicationPatternId,
)
from app.organizational_intelligence.models.approval import (
    ApprovalRecord,
)
from app.organizational_intelligence.models.communication import (
    CommunicationPattern,
)
from app.organizational_intelligence.retrieval.eligibility import (
    derive_eligibility,
    is_retrievable,
    require_eligible,
)
from app.organizational_intelligence.serializers import (
    canonicalize_attributes,
    canonicalize_payload,
    content_fingerprint,
)
from app.organizational_intelligence.supervision.scoring import (
    candidate_strength,
    finding_severity_weight,
    score_communication_match,
)


_NOW = datetime.now(tz=timezone.utc)


def _approval(
    *,
    target_id: uuid.UUID,
    target_kind: str,
    decision: ApprovalDecision = ApprovalDecision.APPROVED,
    authority: ApprovalAuthorityKind = (
        ApprovalAuthorityKind.HUMAN_OPERATOR
    ),
) -> ApprovalRecord:
    return ApprovalRecord(
        approval_id=ApprovalId(uuid.uuid4()),
        target_id=target_id,
        target_kind=target_kind,
        decision=decision,
        authority=authority,
        approver_handle="alice",
        decided_at=_NOW,
    )


# ─── canonicalisation ────────────────────────────────────────────────


def test_canonicalize_payload_sorts_keys() -> None:
    out = canonicalize_payload({"b": 1, "a": {"d": 1, "c": 2}})
    assert list(out.keys()) == ["a", "b"]
    assert list(out["a"].keys()) == ["c", "d"]


def test_content_fingerprint_stable() -> None:
    f1 = content_fingerprint({"a": 1, "b": 2})
    f2 = content_fingerprint({"b": 2, "a": 1})
    assert f1 == f2
    assert len(f1) == 64


def test_canonicalize_attributes_rejects_non_mapping() -> None:
    with pytest.raises(TypeError):
        canonicalize_attributes(["not", "a", "mapping"])  # type: ignore[arg-type]


# ─── eligibility ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "status,expected",
    [
        (MemoryArtifactStatus.APPROVED, True),
        (MemoryArtifactStatus.UNDER_REVIEW, False),
        (MemoryArtifactStatus.CANDIDATE, False),
        (MemoryArtifactStatus.REJECTED, False),
        (MemoryArtifactStatus.SUPERSEDED, False),
        (MemoryArtifactStatus.RETIRED, False),
    ],
)
def test_eligibility_only_for_approved(
    status: MemoryArtifactStatus, expected: bool
) -> None:
    el = derive_eligibility(status)
    assert is_retrievable(el) is expected


def test_require_eligible_raises_when_ineligible() -> None:
    with pytest.raises(IntelligenceAuthorityError):
        require_eligible(
            derive_eligibility(MemoryArtifactStatus.CANDIDATE)
        )


# ─── approval gate ───────────────────────────────────────────────────


def test_promotion_gate_rejects_system_authority() -> None:
    target = uuid.uuid4()
    bad = _approval(
        target_id=target,
        target_kind="candidate_pattern",
        authority=ApprovalAuthorityKind.SYSTEM,
    )
    with pytest.raises(IntelligenceAuthorityError):
        require_approval_for_promotion(
            approval=bad,
            target_id=target,
            target_kind="candidate_pattern",
        )


def test_promotion_gate_requires_approved_decision() -> None:
    target = uuid.uuid4()
    deferred = _approval(
        target_id=target,
        target_kind="candidate_pattern",
        decision=ApprovalDecision.DEFERRED,
    )
    with pytest.raises(IntelligenceApprovalError):
        require_approval_for_promotion(
            approval=deferred,
            target_id=target,
            target_kind="candidate_pattern",
        )


def test_promotion_gate_target_id_must_match() -> None:
    a = _approval(
        target_id=uuid.uuid4(),
        target_kind="candidate_pattern",
    )
    with pytest.raises(IntelligenceAuthorityError):
        require_approval_for_promotion(
            approval=a,
            target_id=uuid.uuid4(),
            target_kind="candidate_pattern",
        )


def test_registration_gate_target_kind_must_match() -> None:
    a = _approval(
        target_id=uuid.uuid4(),
        target_kind="recommendation",
    )
    with pytest.raises(IntelligenceAuthorityError):
        require_approval_for_registration(
            approval=a, target_kind="communication_pattern"
        )


def test_supersession_gate_accepts_predecessor_target() -> None:
    pred = uuid.uuid4()
    succ = uuid.uuid4()
    a = _approval(
        target_id=pred, target_kind="memory_artifact"
    )
    require_approval_for_supersession(
        approval=a,
        predecessor_id=pred,
        successor_id=succ,
        target_kind="memory_artifact",
    )


def test_supersession_gate_accepts_successor_target() -> None:
    pred = uuid.uuid4()
    succ = uuid.uuid4()
    a = _approval(
        target_id=succ, target_kind="memory_artifact"
    )
    require_approval_for_supersession(
        approval=a,
        predecessor_id=pred,
        successor_id=succ,
        target_kind="memory_artifact",
    )


def test_supersession_gate_rejects_unrelated_target() -> None:
    a = _approval(
        target_id=uuid.uuid4(),
        target_kind="memory_artifact",
    )
    with pytest.raises(IntelligenceAuthorityError):
        require_approval_for_supersession(
            approval=a,
            predecessor_id=uuid.uuid4(),
            successor_id=uuid.uuid4(),
            target_kind="memory_artifact",
        )


def test_review_gate_accepts_any_human_decision() -> None:
    target = uuid.uuid4()
    for decision in (
        ApprovalDecision.APPROVED,
        ApprovalDecision.REJECTED,
        ApprovalDecision.DEFERRED,
    ):
        a = _approval(
            target_id=target,
            target_kind="recommendation",
            decision=decision,
        )
        require_approval_for_review(
            approval=a,
            target_id=target,
            target_kind="recommendation",
        )


# ─── supervision scoring ─────────────────────────────────────────────


def test_finding_severity_weight_strict_ordering() -> None:
    weights = [
        finding_severity_weight(s)
        for s in (
            SopFindingSeverity.INFO,
            SopFindingSeverity.LOW,
            SopFindingSeverity.MEDIUM,
            SopFindingSeverity.HIGH,
            SopFindingSeverity.CRITICAL,
        )
    ]
    assert weights == sorted(weights)


def test_candidate_strength_clamped() -> None:
    assert candidate_strength(
        occurrence_count=100, evidence_count=100
    ) == 1.0
    assert candidate_strength(
        occurrence_count=0, evidence_count=0
    ) == 0.0
    with pytest.raises(ValueError):
        candidate_strength(
            occurrence_count=-1, evidence_count=0
        )


def test_communication_match_zero_when_class_not_applicable() -> None:
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
    score, reason = score_communication_match(
        primary_class=TonalityClass.ESCALATED, pattern=pattern
    )
    assert score == 0.0
    assert reason == "primary_class_not_applicable"


def test_communication_match_prefers_canonical_kind() -> None:
    p_empathy = CommunicationPattern(
        pattern_id=CommunicationPatternId(uuid.uuid4()),
        tenant_id=None,
        scope=IntelligenceScope.TENANT,
        kind=CommunicationPatternKind.EMPATHY,
        handle="empathy",
        body="b",
        applicable_classes=(TonalityClass.FRUSTRATED,),
        approval_id=ApprovalId(uuid.uuid4()),
        registered_at=_NOW,
    )
    p_closure = CommunicationPattern(
        pattern_id=CommunicationPatternId(uuid.uuid4()),
        tenant_id=None,
        scope=IntelligenceScope.TENANT,
        kind=CommunicationPatternKind.CLOSURE,
        handle="closure",
        body="b",
        applicable_classes=(TonalityClass.FRUSTRATED,),
        approval_id=ApprovalId(uuid.uuid4()),
        registered_at=_NOW,
    )
    s1, _ = score_communication_match(
        primary_class=TonalityClass.FRUSTRATED, pattern=p_empathy
    )
    s2, _ = score_communication_match(
        primary_class=TonalityClass.FRUSTRATED, pattern=p_closure
    )
    assert s1 > s2


# ─── adaptation markers ──────────────────────────────────────────────


def test_adaptation_marker_catalogue_pinned() -> None:
    assert is_adaptation_event(IntelligenceTraceKind.MEMORY_APPROVE)
    assert is_adaptation_event(IntelligenceTraceKind.MEMORY_REJECT)
    assert is_adaptation_event(IntelligenceTraceKind.MEMORY_SUPERSEDE)
    assert is_adaptation_event(IntelligenceTraceKind.MEMORY_RETIRE)
    assert is_adaptation_event(
        IntelligenceTraceKind.COMMUNICATION_REGISTER
    )
    assert is_adaptation_event(
        IntelligenceTraceKind.RECOMMENDATION_REVIEW
    )
    # Negatives
    assert not is_adaptation_event(
        IntelligenceTraceKind.SOP_INGEST
    )
    assert not is_adaptation_event(
        IntelligenceTraceKind.TONALITY_CLASSIFY
    )
    assert not is_adaptation_event(
        IntelligenceTraceKind.COMMUNICATION_RETRIEVE
    )
    assert not is_adaptation_event(
        IntelligenceTraceKind.PATTERN_ANALYZE
    )


def test_active_adoption_only_approved() -> None:
    assert is_active_adoption(MemoryArtifactStatus.APPROVED)
    for s in (
        MemoryArtifactStatus.CANDIDATE,
        MemoryArtifactStatus.UNDER_REVIEW,
        MemoryArtifactStatus.REJECTED,
        MemoryArtifactStatus.SUPERSEDED,
        MemoryArtifactStatus.RETIRED,
    ):
        assert not is_active_adoption(s)


# ─── correlation helpers ─────────────────────────────────────────────


def test_canonicalize_correlation_handles_dedupes_and_sorts() -> None:
    assert canonicalize_correlation_handles(
        ["b", "a", "", None, "a"]
    ) == (
        "a",
        "b",
    )


def test_build_correlation_seed_skips_empties() -> None:
    assert (
        build_correlation_seed("a", None, "", "b") == "a|b"
    )
