"""Operious AI — Governed Organizational Intelligence Substrate.

This substrate is the **asynchronous governed-evolution layer**.
It is structurally separated from the deterministic operational
runtime (Memory / Governance / Agent / Supervisor / Coordination
/ Boundary / Session / Arbitration). The intelligence substrate:

* may **classify, tag, retrieve, propose, recommend, analyze**;
* MUST NEVER **auto-apply, auto-route, auto-execute, auto-mutate**.

All evolution flows through the canonical pipeline:

    interaction
        → supervision
        → evaluation
        → approval
        → indexing
        → future retrieval

Status transitions out of CANDIDATE / PROPOSED require an
`ApprovalRecord` from a human authority. The `governance/` and
`supervision/` packages inside this substrate are deliberately
**substrate-internal** helpers — they are NOT the operational
governance / supervision substrates (which the intelligence
substrate is forbidden from importing).
"""

from app.organizational_intelligence.contracts import (
    AnalyzeOperationalPatternsRequest,
    AnalyzeOperationalPatternsResult,
    AnalyzeSopRequest,
    AnalyzeSopResult,
    ApprovePatternRequest,
    ApprovePatternResult,
    ApproveRecommendationRequest,
    ApproveRecommendationResult,
    ClassifyTonalityRequest,
    ClassifyTonalityResult,
    GenerateRecommendationRequest,
    GenerateRecommendationResult,
    IngestSopRequest,
    IngestSopResult,
    ListMemoryArtifactsRequest,
    ListMemoryArtifactsResult,
    MemoryEvolutionProposalRequest,
    MemoryEvolutionProposalResult,
    RegisterCommunicationPatternRequest,
    RegisterCommunicationPatternResult,
    RejectPatternRequest,
    RejectPatternResult,
    RetireMemoryArtifactRequest,
    RetireMemoryArtifactResult,
    RetrieveCommunicationPatternsRequest,
    RetrieveCommunicationPatternsResult,
    SupersedeMemoryArtifactRequest,
    SupersedeMemoryArtifactResult,
)
from app.organizational_intelligence.envelopes import (
    IntelligenceEnvelope,
)
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
from app.organizational_intelligence.exceptions import (
    IntelligenceApprovalError,
    IntelligenceAuthorityError,
    IntelligenceConfigurationError,
    IntelligenceError,
    IntelligenceLineageError,
    IntelligenceNotFoundError,
    IntelligencePersistenceError,
    IntelligenceValidationError,
)
from app.organizational_intelligence.identity import (
    ApprovalId,
    ApprovedPatternId,
    CandidatePatternId,
    CommunicationPatternId,
    IntelligenceCorrelationId,
    IntelligenceTraceId,
    MemoryArtifactId,
    MemoryEvolutionProposalId,
    OperationalPatternAnalysisId,
    OperationalPatternObservationId,
    PatternLineageId,
    RecommendationId,
    SopAnalysisId,
    SopFindingId,
    SopId,
    SopVersionId,
    TonalityAnalysisId,
)
from app.organizational_intelligence.models import (
    ApprovalRecord,
    ApprovedPattern,
    CandidatePattern,
    CommunicationPattern,
    CommunicationRetrievalCandidate,
    MemoryEvolutionProposal,
    OperationalPatternAnalysis,
    OperationalPatternObservation,
    OrganizationalMemoryArtifact,
    OrganizationalRecommendation,
    PatternLineage,
    RecommendationRationale,
    RetrievalEligibilityRecord,
    SopAnalysis,
    SopFinding,
    SopVersion,
    StandardOperatingProcedure,
    TonalityAnalysis,
    TonalityTag,
)
from app.organizational_intelligence.persistence import (
    InMemoryIntelligencePersistence,
    IntelligencePersistenceProtocol,
)
from app.organizational_intelligence.runtime import (
    OrganizationalIntelligenceRuntime,
)
from app.organizational_intelligence.taxonomy import (
    IntelligenceMetadataKey,
)
from app.organizational_intelligence.traces import (
    IntelligenceTrace,
    IntelligenceTraceContext,
)

__all__ = [
    "AnalyzeOperationalPatternsRequest",
    "AnalyzeOperationalPatternsResult",
    "AnalyzeSopRequest",
    "AnalyzeSopResult",
    "ApprovalAuthorityKind",
    "ApprovalDecision",
    "ApprovalId",
    "ApprovalRecord",
    "ApprovedPattern",
    "ApprovedPatternId",
    "ApprovePatternRequest",
    "ApprovePatternResult",
    "ApproveRecommendationRequest",
    "ApproveRecommendationResult",
    "CandidatePattern",
    "CandidatePatternId",
    "ClassifyTonalityRequest",
    "ClassifyTonalityResult",
    "CommunicationPattern",
    "CommunicationPatternId",
    "CommunicationPatternKind",
    "CommunicationRetrievalCandidate",
    "GenerateRecommendationRequest",
    "GenerateRecommendationResult",
    "InMemoryIntelligencePersistence",
    "IngestSopRequest",
    "IngestSopResult",
    "IntelligenceApprovalError",
    "IntelligenceAuthorityError",
    "IntelligenceConfigurationError",
    "IntelligenceCorrelationId",
    "IntelligenceEnvelope",
    "IntelligenceError",
    "IntelligenceLineageError",
    "IntelligenceMetadataKey",
    "IntelligenceNotFoundError",
    "IntelligencePersistenceError",
    "IntelligencePersistenceProtocol",
    "IntelligenceScope",
    "IntelligenceTrace",
    "IntelligenceTraceContext",
    "IntelligenceTraceId",
    "IntelligenceTraceKind",
    "IntelligenceValidationError",
    "ListMemoryArtifactsRequest",
    "ListMemoryArtifactsResult",
    "MemoryArtifactId",
    "MemoryArtifactKind",
    "MemoryArtifactStatus",
    "MemoryEvolutionProposal",
    "MemoryEvolutionProposalId",
    "MemoryEvolutionProposalRequest",
    "MemoryEvolutionProposalResult",
    "OperationalPatternAnalysis",
    "OperationalPatternAnalysisId",
    "OperationalPatternKind",
    "OperationalPatternObservation",
    "OperationalPatternObservationId",
    "OrganizationalIntelligenceRuntime",
    "OrganizationalMemoryArtifact",
    "OrganizationalRecommendation",
    "PatternLineage",
    "PatternLineageId",
    "RecommendationId",
    "RecommendationKind",
    "RecommendationRationale",
    "RecommendationStatus",
    "RegisterCommunicationPatternRequest",
    "RegisterCommunicationPatternResult",
    "RejectPatternRequest",
    "RejectPatternResult",
    "RetireMemoryArtifactRequest",
    "RetireMemoryArtifactResult",
    "RetrievalEligibility",
    "RetrievalEligibilityRecord",
    "RetrieveCommunicationPatternsRequest",
    "RetrieveCommunicationPatternsResult",
    "SopAnalysis",
    "SopAnalysisId",
    "SopFinding",
    "SopFindingId",
    "SopFindingKind",
    "SopFindingSeverity",
    "SopId",
    "SopStatus",
    "SopVersion",
    "SopVersionId",
    "StandardOperatingProcedure",
    "SupersedeMemoryArtifactRequest",
    "SupersedeMemoryArtifactResult",
    "TonalityAnalysis",
    "TonalityAnalysisId",
    "TonalityClass",
    "TonalityIntensity",
    "TonalityTag",
]
