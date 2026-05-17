"""Organizational-intelligence identity primitives.

Twelve typed identifiers, all deterministically derivable via UUID5
from a stable seed. Permanent namespace constants pin every
deriver — changing one is a breaking change.
"""

from __future__ import annotations

import uuid
from typing import NewType


# ─── Type aliases ───────────────────────────────────────────────────


SopId = NewType("SopId", uuid.UUID)
SopVersionId = NewType("SopVersionId", uuid.UUID)
SopFindingId = NewType("SopFindingId", uuid.UUID)
SopAnalysisId = NewType("SopAnalysisId", uuid.UUID)
TonalityAnalysisId = NewType("TonalityAnalysisId", uuid.UUID)
CommunicationPatternId = NewType(
    "CommunicationPatternId", uuid.UUID
)
MemoryArtifactId = NewType("MemoryArtifactId", uuid.UUID)
CandidatePatternId = NewType("CandidatePatternId", uuid.UUID)
ApprovedPatternId = NewType("ApprovedPatternId", uuid.UUID)
MemoryEvolutionProposalId = NewType(
    "MemoryEvolutionProposalId", uuid.UUID
)
PatternLineageId = NewType("PatternLineageId", uuid.UUID)
OperationalPatternObservationId = NewType(
    "OperationalPatternObservationId", uuid.UUID
)
OperationalPatternAnalysisId = NewType(
    "OperationalPatternAnalysisId", uuid.UUID
)
RecommendationId = NewType("RecommendationId", uuid.UUID)
ApprovalId = NewType("ApprovalId", uuid.UUID)
IntelligenceTraceId = NewType("IntelligenceTraceId", uuid.UUID)
IntelligenceCorrelationId = NewType(
    "IntelligenceCorrelationId", uuid.UUID
)


# ─── Permanent namespace constants ──────────────────────────────────


_SOP_NAMESPACE = uuid.UUID("01007ec0-0001-4001-8001-000000000001")
_SOP_VERSION_NAMESPACE = uuid.UUID(
    "01007ec0-0002-4002-8002-000000000002"
)
_SOP_FINDING_NAMESPACE = uuid.UUID(
    "01007ec0-0003-4003-8003-000000000003"
)
_SOP_ANALYSIS_NAMESPACE = uuid.UUID(
    "01007ec0-0004-4004-8004-000000000004"
)
_TONALITY_NAMESPACE = uuid.UUID(
    "01007ec0-0005-4005-8005-000000000005"
)
_COMMUNICATION_NAMESPACE = uuid.UUID(
    "01007ec0-0006-4006-8006-000000000006"
)
_ARTIFACT_NAMESPACE = uuid.UUID(
    "01007ec0-0007-4007-8007-000000000007"
)
_CANDIDATE_NAMESPACE = uuid.UUID(
    "01007ec0-0008-4008-8008-000000000008"
)
_APPROVED_PATTERN_NAMESPACE = uuid.UUID(
    "01007ec0-0009-4009-8009-000000000009"
)
_PROPOSAL_NAMESPACE = uuid.UUID(
    "01007ec0-000a-400a-800a-00000000000a"
)
_LINEAGE_NAMESPACE = uuid.UUID(
    "01007ec0-000b-400b-800b-00000000000b"
)
_OBSERVATION_NAMESPACE = uuid.UUID(
    "01007ec0-000c-400c-800c-00000000000c"
)
_PATTERN_ANALYSIS_NAMESPACE = uuid.UUID(
    "01007ec0-000d-400d-800d-00000000000d"
)
_RECOMMENDATION_NAMESPACE = uuid.UUID(
    "01007ec0-000e-400e-800e-00000000000e"
)
_APPROVAL_NAMESPACE = uuid.UUID(
    "01007ec0-000f-400f-800f-00000000000f"
)
_TRACE_NAMESPACE = uuid.UUID(
    "01007ec0-0010-4010-8010-000000000010"
)
_CORRELATION_NAMESPACE = uuid.UUID(
    "01007ec0-0011-4011-8011-000000000011"
)


# ─── Generators (UUID4) ─────────────────────────────────────────────


def generate_sop_id() -> SopId:
    return SopId(uuid.uuid4())


def generate_sop_version_id() -> SopVersionId:
    return SopVersionId(uuid.uuid4())


def generate_sop_finding_id() -> SopFindingId:
    return SopFindingId(uuid.uuid4())


def generate_sop_analysis_id() -> SopAnalysisId:
    return SopAnalysisId(uuid.uuid4())


def generate_tonality_analysis_id() -> TonalityAnalysisId:
    return TonalityAnalysisId(uuid.uuid4())


def generate_communication_pattern_id() -> CommunicationPatternId:
    return CommunicationPatternId(uuid.uuid4())


def generate_memory_artifact_id() -> MemoryArtifactId:
    return MemoryArtifactId(uuid.uuid4())


def generate_candidate_pattern_id() -> CandidatePatternId:
    return CandidatePatternId(uuid.uuid4())


def generate_approved_pattern_id() -> ApprovedPatternId:
    return ApprovedPatternId(uuid.uuid4())


def generate_memory_evolution_proposal_id() -> (
    MemoryEvolutionProposalId
):
    return MemoryEvolutionProposalId(uuid.uuid4())


def generate_pattern_lineage_id() -> PatternLineageId:
    return PatternLineageId(uuid.uuid4())


def generate_operational_pattern_observation_id() -> (
    OperationalPatternObservationId
):
    return OperationalPatternObservationId(uuid.uuid4())


def generate_operational_pattern_analysis_id() -> (
    OperationalPatternAnalysisId
):
    return OperationalPatternAnalysisId(uuid.uuid4())


def generate_recommendation_id() -> RecommendationId:
    return RecommendationId(uuid.uuid4())


def generate_approval_id() -> ApprovalId:
    return ApprovalId(uuid.uuid4())


def generate_trace_id() -> IntelligenceTraceId:
    return IntelligenceTraceId(uuid.uuid4())


def generate_correlation_id() -> IntelligenceCorrelationId:
    return IntelligenceCorrelationId(uuid.uuid4())


# ─── Replay-safe deterministic UUID5 derivers ───────────────────────


def derive_sop_id(
    *,
    tenant_id: str | None,
    external_handle: str,
) -> SopId:
    if not external_handle:
        raise ValueError(
            "derive_sop_id requires a non-empty external_handle"
        )
    return SopId(
        uuid.uuid5(
            _SOP_NAMESPACE,
            f"{tenant_id or ''}|{external_handle}",
        )
    )


def derive_sop_version_id(
    *, sop_id: uuid.UUID, version: int
) -> SopVersionId:
    if version < 1:
        raise ValueError("version must be >= 1")
    return SopVersionId(
        uuid.uuid5(_SOP_VERSION_NAMESPACE, f"{sop_id}|{version}")
    )


def derive_sop_finding_id(
    *,
    sop_id: uuid.UUID,
    version: int,
    ordinal: int,
) -> SopFindingId:
    return SopFindingId(
        uuid.uuid5(
            _SOP_FINDING_NAMESPACE,
            f"{sop_id}|{version}|{ordinal}",
        )
    )


def derive_sop_analysis_id(
    *,
    sop_id: uuid.UUID,
    version: int,
) -> SopAnalysisId:
    return SopAnalysisId(
        uuid.uuid5(
            _SOP_ANALYSIS_NAMESPACE,
            f"{sop_id}|{version}",
        )
    )


def derive_tonality_analysis_id(
    *,
    content_fingerprint: str,
    correlation: str | None,
) -> TonalityAnalysisId:
    if not content_fingerprint:
        raise ValueError(
            "derive_tonality_analysis_id requires content_fingerprint"
        )
    return TonalityAnalysisId(
        uuid.uuid5(
            _TONALITY_NAMESPACE,
            f"{content_fingerprint}|{correlation or ''}",
        )
    )


def derive_communication_pattern_id(
    *,
    tenant_id: str | None,
    pattern_handle: str,
) -> CommunicationPatternId:
    if not pattern_handle:
        raise ValueError(
            "derive_communication_pattern_id requires pattern_handle"
        )
    return CommunicationPatternId(
        uuid.uuid5(
            _COMMUNICATION_NAMESPACE,
            f"{tenant_id or ''}|{pattern_handle}",
        )
    )


def derive_memory_artifact_id(
    *,
    kind: str,
    content_fingerprint: str,
) -> MemoryArtifactId:
    if not content_fingerprint:
        raise ValueError(
            "derive_memory_artifact_id requires content_fingerprint"
        )
    return MemoryArtifactId(
        uuid.uuid5(
            _ARTIFACT_NAMESPACE,
            f"{kind}|{content_fingerprint}",
        )
    )


def derive_candidate_pattern_id(
    *, observation_seed: str
) -> CandidatePatternId:
    if not observation_seed:
        raise ValueError(
            "derive_candidate_pattern_id requires observation_seed"
        )
    return CandidatePatternId(
        uuid.uuid5(_CANDIDATE_NAMESPACE, observation_seed)
    )


def derive_approved_pattern_id(
    *,
    candidate_id: uuid.UUID,
    approval_id: uuid.UUID,
) -> ApprovedPatternId:
    return ApprovedPatternId(
        uuid.uuid5(
            _APPROVED_PATTERN_NAMESPACE,
            f"{candidate_id}|{approval_id}",
        )
    )


def derive_memory_evolution_proposal_id(
    *, candidate_id: uuid.UUID
) -> MemoryEvolutionProposalId:
    return MemoryEvolutionProposalId(
        uuid.uuid5(_PROPOSAL_NAMESPACE, str(candidate_id))
    )


def derive_pattern_lineage_id(
    *, root_artifact_id: uuid.UUID
) -> PatternLineageId:
    return PatternLineageId(
        uuid.uuid5(_LINEAGE_NAMESPACE, str(root_artifact_id))
    )


def derive_operational_pattern_observation_id(
    *, seed: str
) -> OperationalPatternObservationId:
    if not seed:
        raise ValueError(
            "derive_operational_pattern_observation_id requires seed"
        )
    return OperationalPatternObservationId(
        uuid.uuid5(_OBSERVATION_NAMESPACE, seed)
    )


def derive_operational_pattern_analysis_id(
    *, seed: str
) -> OperationalPatternAnalysisId:
    if not seed:
        raise ValueError(
            "derive_operational_pattern_analysis_id requires seed"
        )
    return OperationalPatternAnalysisId(
        uuid.uuid5(_PATTERN_ANALYSIS_NAMESPACE, seed)
    )


def derive_recommendation_id(
    *,
    scope: str,
    content_fingerprint: str,
) -> RecommendationId:
    if not content_fingerprint:
        raise ValueError(
            "derive_recommendation_id requires content_fingerprint"
        )
    return RecommendationId(
        uuid.uuid5(
            _RECOMMENDATION_NAMESPACE,
            f"{scope}|{content_fingerprint}",
        )
    )


def derive_approval_id(
    *,
    target_id: uuid.UUID,
    decision: str,
    approver_handle: str,
    decided_at_iso: str,
) -> ApprovalId:
    if not approver_handle:
        raise ValueError(
            "derive_approval_id requires approver_handle"
        )
    if not decided_at_iso:
        raise ValueError(
            "derive_approval_id requires decided_at_iso"
        )
    return ApprovalId(
        uuid.uuid5(
            _APPROVAL_NAMESPACE,
            f"{target_id}|{decision}|{approver_handle}|{decided_at_iso}",
        )
    )


def derive_trace_id(*, seed: str) -> IntelligenceTraceId:
    if not seed:
        raise ValueError("derive_trace_id requires seed")
    return IntelligenceTraceId(
        uuid.uuid5(_TRACE_NAMESPACE, seed)
    )


def derive_correlation_id(
    *, seed: str
) -> IntelligenceCorrelationId:
    if not seed:
        raise ValueError("derive_correlation_id requires seed")
    return IntelligenceCorrelationId(
        uuid.uuid5(_CORRELATION_NAMESPACE, seed)
    )


__all__ = [
    "ApprovalId",
    "ApprovedPatternId",
    "CandidatePatternId",
    "CommunicationPatternId",
    "IntelligenceCorrelationId",
    "IntelligenceTraceId",
    "MemoryArtifactId",
    "MemoryEvolutionProposalId",
    "OperationalPatternAnalysisId",
    "OperationalPatternObservationId",
    "PatternLineageId",
    "RecommendationId",
    "SopAnalysisId",
    "SopFindingId",
    "SopId",
    "SopVersionId",
    "TonalityAnalysisId",
    "derive_approval_id",
    "derive_approved_pattern_id",
    "derive_candidate_pattern_id",
    "derive_communication_pattern_id",
    "derive_correlation_id",
    "derive_memory_artifact_id",
    "derive_memory_evolution_proposal_id",
    "derive_operational_pattern_analysis_id",
    "derive_operational_pattern_observation_id",
    "derive_pattern_lineage_id",
    "derive_recommendation_id",
    "derive_sop_analysis_id",
    "derive_sop_finding_id",
    "derive_sop_id",
    "derive_sop_version_id",
    "derive_tonality_analysis_id",
    "derive_trace_id",
    "generate_approval_id",
    "generate_approved_pattern_id",
    "generate_candidate_pattern_id",
    "generate_communication_pattern_id",
    "generate_correlation_id",
    "generate_memory_artifact_id",
    "generate_memory_evolution_proposal_id",
    "generate_operational_pattern_analysis_id",
    "generate_operational_pattern_observation_id",
    "generate_pattern_lineage_id",
    "generate_recommendation_id",
    "generate_sop_analysis_id",
    "generate_sop_finding_id",
    "generate_sop_id",
    "generate_sop_version_id",
    "generate_tonality_analysis_id",
    "generate_trace_id",
]
