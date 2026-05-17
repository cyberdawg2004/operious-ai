"""Wire-format pinning for intelligence-substrate enums.

Renaming a value here is a breaking change. These tests pin the
catalogue.
"""

from __future__ import annotations

import pytest

from app.organizational_intelligence.enums import (
    ApprovalAuthorityKind,
    ApprovalDecision,
    CommunicationPatternKind,
    IntelligenceScope,
    IntelligenceTraceKind,
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


def _values(enum_cls) -> set[str]:
    return {member.value for member in enum_cls}


@pytest.mark.parametrize(
    "enum_cls,expected",
    [
        (
            SopStatus,
            {
                "draft",
                "ingested",
                "analyzed",
                "recommended",
                "approved",
                "superseded",
                "archived",
            },
        ),
        (
            SopFindingKind,
            {
                "ambiguity",
                "contradiction",
                "escalation_gap",
                "missing_authority",
                "scope_drift",
                "outdated_reference",
            },
        ),
        (
            SopFindingSeverity,
            {"info", "low", "medium", "high", "critical"},
        ),
        (
            TonalityClass,
            {
                "neutral",
                "calm",
                "urgent",
                "frustrated",
                "escalated",
                "distressed",
                "positive",
                "formal",
                "casual",
            },
        ),
        (
            TonalityIntensity,
            {"low", "moderate", "high", "critical"},
        ),
        (
            CommunicationPatternKind,
            {
                "acknowledgement",
                "empathy",
                "de_escalation",
                "information_delivery",
                "apology",
                "escalation_handoff",
                "closure",
            },
        ),
        (
            OperationalPatternKind,
            {
                "escalation_failure",
                "sop_conflict",
                "communication_degradation",
                "operational_drift",
                "recurring_defect",
                "bottleneck",
            },
        ),
        (
            RecommendationKind,
            {
                "sop_optimization",
                "escalation_improvement",
                "communication_improvement",
                "ambiguity_resolution",
                "bottleneck_relief",
                "pattern_adoption",
                "pattern_retirement",
            },
        ),
        (
            RecommendationStatus,
            {
                "proposed",
                "reviewed",
                "approved",
                "rejected",
                "deferred",
                "superseded",
            },
        ),
        (
            MemoryArtifactKind,
            {
                "sop_fragment",
                "communication_pattern",
                "escalation_pattern",
                "operational_observation",
                "pattern_annotation",
            },
        ),
        (
            MemoryArtifactStatus,
            {
                "candidate",
                "under_review",
                "approved",
                "rejected",
                "superseded",
                "retired",
            },
        ),
        (
            RetrievalEligibility,
            {
                "ineligible",
                "pending",
                "eligible",
                "restricted",
            },
        ),
        (
            ApprovalDecision,
            {"approved", "rejected", "deferred"},
        ),
        (
            ApprovalAuthorityKind,
            {"human_operator", "human_reviewer", "system"},
        ),
        (
            IntelligenceScope,
            {"tenant", "domain", "global"},
        ),
        (
            IntelligenceTraceKind,
            {
                "sop_ingest",
                "sop_analyze",
                "sop_list",
                "tonality_classify",
                "communication_retrieve",
                "communication_register",
                "memory_propose",
                "memory_approve",
                "memory_reject",
                "memory_supersede",
                "memory_retire",
                "memory_list",
                "pattern_analyze",
                "recommendation_generate",
                "recommendation_review",
                "lookup",
            },
        ),
    ],
)
def test_enum_values_pinned(enum_cls, expected: set[str]) -> None:
    assert _values(enum_cls) == expected
