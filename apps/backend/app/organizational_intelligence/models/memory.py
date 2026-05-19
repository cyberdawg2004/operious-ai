"""Organizational-memory value objects.

THE central architectural rule of Sprint O lives here:

    Organizational intelligence evolves through MEMORY EVOLUTION,
    not through runtime mutation.

The models below are the substrate's vocabulary for that
evolution. Notice the pipeline they enforce:

    OperationalPatternObservation
        ↓
    CandidatePattern         ← extracted, classification only
        ↓
    MemoryEvolutionProposal  ← a structured human-review packet
        ↓
    ApprovalRecord           ← human decision (external)
        ↓
    ApprovedPattern          ← retrieval-eligible
        ↓
    OrganizationalMemoryArtifact / RetrievalEligibilityRecord

Every transition is **explicit**. There is no auto-promotion path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.organizational_intelligence.enums import (
    IntelligenceScope,
    MemoryArtifactKind,
    MemoryArtifactStatus,
    RetrievalEligibility,
)
from app.organizational_intelligence.identity import (
    ApprovalId as ApprovalId,
    ApprovedPatternId as ApprovedPatternId,
    CandidatePatternId as CandidatePatternId,
    MemoryArtifactId,
    MemoryEvolutionProposalId,
    PatternLineageId,
)


@dataclass(frozen=True, slots=True)
class CandidatePattern:
    """Extracted, unevaluated candidate pattern.

    Attributes:
        candidate_id:        Stable identifier (UUID5-derivable
                              from observation seed).
        observation_seed:    Deterministic seed used to derive
                              the candidate id.
        kind:                Coarse classification.
        summary:             Short human-readable summary.
        body:                Canonical body text.
        content_fingerprint: SHA-256 of the canonical body.
        evidence:            Tuple of opaque evidence handles
                              (e.g. session ids, supervisor
                              evaluation ids).
        extracted_at:        UTC timestamp of extraction.
        extractor_signature: Identifier of the deterministic
                              extractor that produced this
                              candidate.
        scope:               Authority-scope classification.
        tenant_id:           Tenant scope.
        attributes:          Canonical metadata payload.
    """

    candidate_id: CandidatePatternId
    observation_seed: str
    kind: MemoryArtifactKind
    summary: str
    body: str
    content_fingerprint: str
    evidence: tuple[str, ...]
    extracted_at: datetime
    extractor_signature: str
    scope: IntelligenceScope = IntelligenceScope.TENANT
    tenant_id: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.summary:
            raise ValueError("CandidatePattern.summary must be non-empty")
        if not self.body:
            raise ValueError("CandidatePattern.body must be non-empty")
        if not self.observation_seed:
            raise ValueError(
                "CandidatePattern.observation_seed must be non-empty"
            )
        if not self.content_fingerprint:
            raise ValueError(
                "CandidatePattern.content_fingerprint must be non-empty"
            )
        if not self.extractor_signature:
            raise ValueError(
                "CandidatePattern.extractor_signature must be non-empty"
            )
        if self.extracted_at.tzinfo is None:
            raise ValueError(
                "CandidatePattern.extracted_at must be tz-aware"
            )


@dataclass(frozen=True, slots=True)
class MemoryEvolutionProposal:
    """Structured packet sent to a human reviewer.

    Attributes:
        proposal_id:        Stable identifier (UUID5-derivable
                             from candidate id).
        candidate_id:       The candidate the proposal is built
                             from.
        proposed_at:        UTC timestamp.
        rationale:          Free-form human-readable rationale
                             constructed by the substrate from
                             evidence (descriptive only).
        evidence_summary:   Sorted, deduplicated tuple of evidence
                             handles (canonicalised).
        status:             Always ``CANDIDATE`` until the
                             approval pipeline converts the
                             candidate to an APPROVED pattern.
        metadata:           Canonical metadata payload.
    """

    proposal_id: MemoryEvolutionProposalId
    candidate_id: CandidatePatternId
    proposed_at: datetime
    rationale: str
    evidence_summary: tuple[str, ...]
    status: MemoryArtifactStatus = (
        MemoryArtifactStatus.CANDIDATE
    )
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.rationale:
            raise ValueError(
                "MemoryEvolutionProposal.rationale must be non-empty"
            )
        if self.proposed_at.tzinfo is None:
            raise ValueError(
                "MemoryEvolutionProposal.proposed_at must be tz-aware"
            )


@dataclass(frozen=True, slots=True)
class ApprovedPattern:
    """A candidate that has been promoted via an `ApprovalRecord`.

    Attributes:
        approved_pattern_id: Stable identifier (UUID5-derivable
                              from candidate + approval).
        candidate_id:        Source candidate.
        approval_id:         The approval that promoted it.
        approved_at:         UTC timestamp.
        body:                Canonical body text (carried over).
        kind:                Memory-artifact classification.
        scope:               Authority-scope classification.
        tenant_id:           Tenant scope.
        approver_handle:     Free-form approver attribution.
        attributes:          Canonical metadata payload.
    """

    approved_pattern_id: ApprovedPatternId
    candidate_id: CandidatePatternId
    approval_id: ApprovalId
    approved_at: datetime
    body: str
    kind: MemoryArtifactKind
    scope: IntelligenceScope
    tenant_id: str | None = None
    approver_handle: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.body:
            raise ValueError(
                "ApprovedPattern.body must be non-empty"
            )
        if self.approved_at.tzinfo is None:
            raise ValueError(
                "ApprovedPattern.approved_at must be tz-aware"
            )


@dataclass(frozen=True, slots=True)
class PatternLineage:
    """Immutable ancestry record for a memory artifact.

    Attributes:
        lineage_id:           Stable lineage identifier
                               (UUID5-derivable from root artifact).
        artifact_id:          The artifact this lineage anchors.
        root_artifact_id:     Topmost ancestor.
        parent_artifact_id:   Immediate predecessor; ``None`` for
                               root.
        ancestor_artifact_ids: Ordered ancestry chain (root-first).
        depth:                Length of the ancestry chain.
    """

    lineage_id: PatternLineageId
    artifact_id: MemoryArtifactId
    root_artifact_id: MemoryArtifactId
    parent_artifact_id: MemoryArtifactId | None
    ancestor_artifact_ids: tuple[MemoryArtifactId, ...]
    depth: int

    def __post_init__(self) -> None:
        if self.artifact_id in self.ancestor_artifact_ids:
            raise ValueError(
                "PatternLineage cycle detected"
            )
        if self.depth != len(self.ancestor_artifact_ids):
            raise ValueError(
                "PatternLineage.depth must equal "
                "len(ancestor_artifact_ids)"
            )
        if (
            self.parent_artifact_id is not None
            and (
                not self.ancestor_artifact_ids
                or self.ancestor_artifact_ids[-1]
                != self.parent_artifact_id
            )
        ):
            raise ValueError(
                "PatternLineage.parent_artifact_id must equal the "
                "last ancestor"
            )

    @property
    def is_root(self) -> bool:
        return self.parent_artifact_id is None


@dataclass(frozen=True, slots=True)
class RetrievalEligibilityRecord:
    """Whether an artifact may participate in retrieval.

    The substrate **derives** eligibility from approval status;
    eligibility is never set autonomously. Switching to
    ``ELIGIBLE`` requires an `ApprovalRecord`. Switching to
    ``RESTRICTED`` / ``INELIGIBLE`` requires either an explicit
    rejection or a supersession event.
    """

    artifact_id: MemoryArtifactId
    eligibility: RetrievalEligibility
    derived_from_approval_id: ApprovalId | None
    derived_at: datetime
    rationale: str | None = None

    def __post_init__(self) -> None:
        if self.derived_at.tzinfo is None:
            raise ValueError(
                "RetrievalEligibilityRecord.derived_at must be "
                "tz-aware"
            )


@dataclass(frozen=True, slots=True)
class OrganizationalMemoryArtifact:
    """Apex immutable organizational-memory artifact.

    The artifact is the **persisted** representation of a
    pattern (pre- or post-approval). It carries explicit lineage,
    explicit approval ancestry, and explicit retrieval eligibility.
    """

    artifact_id: MemoryArtifactId
    kind: MemoryArtifactKind
    scope: IntelligenceScope
    tenant_id: str | None
    status: MemoryArtifactStatus
    body: str
    content_fingerprint: str
    candidate_id: CandidatePatternId | None
    approved_pattern_id: ApprovedPatternId | None
    approval_id: ApprovalId | None
    proposal_id: MemoryEvolutionProposalId | None
    lineage: PatternLineage
    eligibility: RetrievalEligibility
    created_at: datetime
    updated_at: datetime
    revision: int = 1
    superseded_by: MemoryArtifactId | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            raise ValueError(
                "OrganizationalMemoryArtifact.created_at must be "
                "tz-aware"
            )
        if self.updated_at.tzinfo is None:
            raise ValueError(
                "OrganizationalMemoryArtifact.updated_at must be "
                "tz-aware"
            )
        if self.revision < 1:
            raise ValueError("revision must be >= 1")
        if (
            self.status is MemoryArtifactStatus.APPROVED
            and self.approval_id is None
        ):
            raise ValueError(
                "APPROVED artifacts require an approval_id"
            )
        if (
            self.eligibility is RetrievalEligibility.ELIGIBLE
            and self.status is not MemoryArtifactStatus.APPROVED
        ):
            raise ValueError(
                "Only APPROVED artifacts may be ELIGIBLE for "
                "retrieval"
            )
        if self.lineage.artifact_id != self.artifact_id:
            raise ValueError(
                "OrganizationalMemoryArtifact.lineage.artifact_id "
                "mismatch"
            )

    @property
    def is_retrieval_eligible(self) -> bool:
        return self.eligibility is RetrievalEligibility.ELIGIBLE


__all__ = [
    "ApprovedPattern",
    "CandidatePattern",
    "MemoryEvolutionProposal",
    "OrganizationalMemoryArtifact",
    "PatternLineage",
    "RetrievalEligibilityRecord",
]
