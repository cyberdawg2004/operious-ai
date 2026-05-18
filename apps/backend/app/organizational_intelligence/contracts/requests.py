"""Typed runtime requests for the intelligence substrate."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.identity import (
    AuthorityContext,
    check_tenant_authority_coexistence,
)
from app.organizational_intelligence.enums import (
    CommunicationPatternKind,
    IntelligenceScope,
    MemoryArtifactKind,
    OperationalPatternKind,
    RecommendationKind,
    TonalityClass,
)
from app.organizational_intelligence.identity import (
    ApprovalId,
    CandidatePatternId,
    MemoryArtifactId,
    RecommendationId,
    SopId,
)
from app.organizational_intelligence.models.approval import (
    ApprovalRecord,
)
from app.organizational_intelligence.models.pattern import (
    OperationalPatternObservation,
)
from app.organizational_intelligence.models.recommendation import (
    RecommendationRationale,
)


# ─── SOP ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class IngestSopRequest:
    """Ingest a new SOP version.

    The substrate canonicalises the body, derives a content
    fingerprint, and stores the record as ``INGESTED``. It does
    NOT auto-analyze or auto-approve.
    """

    external_handle: str
    title: str
    body: str
    tenant_id: str | None = None
    scope: IntelligenceScope = IntelligenceScope.TENANT
    author_handle: str | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    authority: AuthorityContext | None = None

    def __post_init__(self) -> None:
        check_tenant_authority_coexistence(
            contract_name="IngestSopRequest",
            authority=self.authority,
            tenant_id=self.tenant_id,
        )


@dataclass(frozen=True, slots=True)
class AnalyzeSopRequest:
    """Run the deterministic analyzer over an ingested SOP."""

    sop_id: SopId
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


# ─── Tonality / communication ─────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ClassifyTonalityRequest:
    """Classify a piece of customer/operator content."""

    content: str
    tenant_id: str | None = None
    correlation_hint: str | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    authority: AuthorityContext | None = None

    def __post_init__(self) -> None:
        check_tenant_authority_coexistence(
            contract_name="ClassifyTonalityRequest",
            authority=self.authority,
            tenant_id=self.tenant_id,
        )


@dataclass(frozen=True, slots=True)
class RegisterCommunicationPatternRequest:
    """Register a new APPROVED communication pattern.

    The substrate refuses to register a pattern without an
    `ApprovalRecord`. The approval record's ``decision`` MUST be
    APPROVED.
    """

    handle: str
    body: str
    kind: CommunicationPatternKind
    applicable_classes: tuple[TonalityClass, ...]
    approval: ApprovalRecord
    tenant_id: str | None = None
    scope: IntelligenceScope = IntelligenceScope.TENANT
    author_handle: str | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    authority: AuthorityContext | None = None

    def __post_init__(self) -> None:
        check_tenant_authority_coexistence(
            contract_name="RegisterCommunicationPatternRequest",
            authority=self.authority,
            tenant_id=self.tenant_id,
        )


@dataclass(frozen=True, slots=True)
class RetrieveCommunicationPatternsRequest:
    """Retrieve approved patterns matching a tonality classification."""

    primary_class: TonalityClass
    desired_kinds: tuple[CommunicationPatternKind, ...] = ()
    tenant_id: str | None = None
    scope: IntelligenceScope | None = None
    limit: int = 5
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    authority: AuthorityContext | None = None

    def __post_init__(self) -> None:
        check_tenant_authority_coexistence(
            contract_name="RetrieveCommunicationPatternsRequest",
            authority=self.authority,
            tenant_id=self.tenant_id,
        )


# ─── Memory evolution ─────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class MemoryEvolutionProposalRequest:
    """Propose a candidate pattern from one or more observations.

    The substrate constructs a `CandidatePattern`, derives a
    `MemoryEvolutionProposal`, and persists both. Status remains
    ``CANDIDATE`` — only an explicit `ApprovePatternRequest` lifts
    it.
    """

    observation_seed: str
    summary: str
    body: str
    kind: MemoryArtifactKind
    evidence: tuple[str, ...] = ()
    tenant_id: str | None = None
    scope: IntelligenceScope = IntelligenceScope.TENANT
    rationale: str | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    authority: AuthorityContext | None = None

    def __post_init__(self) -> None:
        check_tenant_authority_coexistence(
            contract_name="MemoryEvolutionProposalRequest",
            authority=self.authority,
            tenant_id=self.tenant_id,
        )


@dataclass(frozen=True, slots=True)
class ApprovePatternRequest:
    """Promote a candidate pattern to APPROVED.

    The substrate enforces:

    * ``approval.decision == APPROVED``,
    * ``approval.target_id == candidate_id``,
    * ``approval.target_kind == "candidate_pattern"``.
    """

    candidate_id: CandidatePatternId
    approval: ApprovalRecord
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RejectPatternRequest:
    """Explicitly reject a candidate pattern."""

    candidate_id: CandidatePatternId
    approval: ApprovalRecord
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SupersedeMemoryArtifactRequest:
    """Replace an APPROVED artifact with a newer APPROVED version."""

    predecessor_id: MemoryArtifactId
    successor_id: MemoryArtifactId
    approval: ApprovalRecord
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RetireMemoryArtifactRequest:
    """Retire an artifact from retrieval eligibility.

    Retirement is **explicit**. The substrate refuses to retire
    without an `ApprovalRecord`.
    """

    artifact_id: MemoryArtifactId
    approval: ApprovalRecord
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ListMemoryArtifactsRequest:
    """List memory artifacts; supports filtering."""

    tenant_id: str | None = None
    kind: MemoryArtifactKind | None = None
    eligible_only: bool = True
    limit: int = 50
    offset: int = 0
    correlation_id: str | None = None
    request_id: str | None = None
    authority: AuthorityContext | None = None

    def __post_init__(self) -> None:
        check_tenant_authority_coexistence(
            contract_name="ListMemoryArtifactsRequest",
            authority=self.authority,
            tenant_id=self.tenant_id,
        )


# ─── Operational patterns / recommendations ───────────────────────


@dataclass(frozen=True, slots=True)
class AnalyzeOperationalPatternsRequest:
    """Run pattern analysis on a batch of operational observations.

    Observations are ALREADY constructed by the caller — the
    substrate does not reach into upstream substrates to fetch
    them.
    """

    seed: str
    observations: tuple[OperationalPatternObservation, ...]
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GenerateRecommendationRequest:
    """Generate one inspectable recommendation.

    Status is ALWAYS ``PROPOSED`` on creation. The runtime never
    auto-approves.
    """

    title: str
    body: str
    kind: RecommendationKind
    target_handle: str
    rationale: RecommendationRationale
    tenant_id: str | None = None
    scope: IntelligenceScope = IntelligenceScope.TENANT
    related_pattern_kinds: tuple[
        OperationalPatternKind, ...
    ] = ()
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    authority: AuthorityContext | None = None

    def __post_init__(self) -> None:
        check_tenant_authority_coexistence(
            contract_name="GenerateRecommendationRequest",
            authority=self.authority,
            tenant_id=self.tenant_id,
        )


@dataclass(frozen=True, slots=True)
class ApproveRecommendationRequest:
    """Record a human review decision against a recommendation.

    The decision may be APPROVED, REJECTED, or DEFERRED.
    Even an APPROVED recommendation is **not auto-applied** —
    application is the caller's responsibility (with an explicit
    runtime call elsewhere).
    """

    recommendation_id: RecommendationId
    approval: ApprovalRecord
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


# Re-exports
ApprovalId  # noqa: B018


__all__ = [
    "AnalyzeOperationalPatternsRequest",
    "AnalyzeSopRequest",
    "ApprovePatternRequest",
    "ApproveRecommendationRequest",
    "ClassifyTonalityRequest",
    "GenerateRecommendationRequest",
    "IngestSopRequest",
    "ListMemoryArtifactsRequest",
    "MemoryEvolutionProposalRequest",
    "RegisterCommunicationPatternRequest",
    "RejectPatternRequest",
    "RetireMemoryArtifactRequest",
    "RetrieveCommunicationPatternsRequest",
    "SupersedeMemoryArtifactRequest",
]
