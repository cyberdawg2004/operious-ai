"""Organizational-intelligence wire-format vocabulary.

Sprint O discipline:

* Every vocabulary below is **descriptive** — none of it directs
  the runtime to do something. The substrate may classify, tag,
  retrieve, or recommend; it never executes, routes, mutates,
  or auto-applies anything.
* Every status / lifecycle vocabulary preserves the central
  invariant: **artifacts are CANDIDATE / PROPOSED until an
  explicit approval flow lifts them to APPROVED**. There is no
  auto-promotion path.
* Every wire value is pinned. `tests/test_intelligence_invariants.py`
  pins the catalogue so any rename fails at import.
"""

from __future__ import annotations

from enum import StrEnum


# ─── SOP ingestion / analysis ──────────────────────────────────────


class SopStatus(StrEnum):
    """Lifecycle of a Standard Operating Procedure artifact.

    DRAFT       — caller-supplied content; not yet ingested.
    INGESTED    — substrate-canonicalised; analysis pending.
    ANALYZED    — analysis complete; findings attached.
    RECOMMENDED — recommendation(s) generated; awaiting human review.
    APPROVED    — human-approved; eligible for downstream retrieval.
    SUPERSEDED  — replaced by a newer approved version.
    ARCHIVED    — terminal cold-storage classification.
    """

    DRAFT = "draft"
    INGESTED = "ingested"
    ANALYZED = "analyzed"
    RECOMMENDED = "recommended"
    APPROVED = "approved"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class SopFindingKind(StrEnum):
    """Closed vocabulary for SOP-analysis findings.

    All findings are **observational**. They never imply automatic
    correction.
    """

    AMBIGUITY = "ambiguity"
    CONTRADICTION = "contradiction"
    ESCALATION_GAP = "escalation_gap"
    MISSING_AUTHORITY = "missing_authority"
    SCOPE_DRIFT = "scope_drift"
    OUTDATED_REFERENCE = "outdated_reference"


class SopFindingSeverity(StrEnum):
    """Bounded severity classification for SOP findings."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ─── Tonality / communication ─────────────────────────────────────


class TonalityClass(StrEnum):
    """Classification of customer/operator tonality.

    These are descriptive tags — they never instruct the runtime
    to take a particular action.
    """

    NEUTRAL = "neutral"
    CALM = "calm"
    URGENT = "urgent"
    FRUSTRATED = "frustrated"
    ESCALATED = "escalated"
    DISTRESSED = "distressed"
    POSITIVE = "positive"
    FORMAL = "formal"
    CASUAL = "casual"


class TonalityIntensity(StrEnum):
    """Bounded intensity of a tonality classification."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class CommunicationPatternKind(StrEnum):
    """Approved-pattern classification.

    Communication patterns are **retrieved**, never invented at
    runtime.
    """

    ACKNOWLEDGEMENT = "acknowledgement"
    EMPATHY = "empathy"
    DE_ESCALATION = "de_escalation"
    INFORMATION_DELIVERY = "information_delivery"
    APOLOGY = "apology"
    ESCALATION_HANDOFF = "escalation_handoff"
    CLOSURE = "closure"


# ─── Operational patterns ─────────────────────────────────────────


class OperationalPatternKind(StrEnum):
    """Recurring-pattern classification (analysis only).

    The substrate may surface these patterns. It never auto-fixes
    them.
    """

    ESCALATION_FAILURE = "escalation_failure"
    SOP_CONFLICT = "sop_conflict"
    COMMUNICATION_DEGRADATION = "communication_degradation"
    OPERATIONAL_DRIFT = "operational_drift"
    RECURRING_DEFECT = "recurring_defect"
    BOTTLENECK = "bottleneck"


# ─── Recommendations ──────────────────────────────────────────────


class RecommendationKind(StrEnum):
    """Recommendation-classification vocabulary."""

    SOP_OPTIMIZATION = "sop_optimization"
    ESCALATION_IMPROVEMENT = "escalation_improvement"
    COMMUNICATION_IMPROVEMENT = "communication_improvement"
    AMBIGUITY_RESOLUTION = "ambiguity_resolution"
    BOTTLENECK_RELIEF = "bottleneck_relief"
    PATTERN_ADOPTION = "pattern_adoption"
    PATTERN_RETIREMENT = "pattern_retirement"


class RecommendationStatus(StrEnum):
    """Lifecycle of an organizational recommendation.

    PROPOSED → REVIEWED → APPROVED / REJECTED / DEFERRED.
    The substrate **never** transitions out of PROPOSED on its own.
    """

    PROPOSED = "proposed"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    SUPERSEDED = "superseded"


# ─── Memory evolution ─────────────────────────────────────────────


class MemoryArtifactKind(StrEnum):
    """Coarse classification of organizational-memory artifacts."""

    SOP_FRAGMENT = "sop_fragment"
    COMMUNICATION_PATTERN = "communication_pattern"
    ESCALATION_PATTERN = "escalation_pattern"
    OPERATIONAL_OBSERVATION = "operational_observation"
    PATTERN_ANNOTATION = "pattern_annotation"


class MemoryArtifactStatus(StrEnum):
    """Lifecycle of an organizational-memory artifact.

    CANDIDATE       — extracted but unevaluated.
    UNDER_REVIEW    — explicitly handed to human review.
    APPROVED        — human-approved; eligible for retrieval.
    REJECTED        — human-rejected; ineligible forever.
    SUPERSEDED      — replaced by a newer approved version.
    RETIRED         — explicitly removed from retrieval eligibility.
    """

    CANDIDATE = "candidate"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


class RetrievalEligibility(StrEnum):
    """Whether an artifact may participate in future retrieval.

    Eligibility is a deterministic projection of approval status.
    The substrate NEVER sets eligibility autonomously — it is
    derived from `MemoryArtifactStatus` via the approval-gate.
    """

    INELIGIBLE = "ineligible"
    PENDING = "pending"
    ELIGIBLE = "eligible"
    RESTRICTED = "restricted"


class ApprovalDecision(StrEnum):
    """Human approval decision."""

    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class ApprovalAuthorityKind(StrEnum):
    """Who approved.

    HUMAN_OPERATOR — the canonical authority.
    HUMAN_REVIEWER — a delegated reviewer with bounded scope.
    SYSTEM         — substrate-internal record-keeping
                     (NEVER an approver of its own evolution;
                     reserved for bookkeeping events, e.g.
                     superseding an artifact via a new approval).
    """

    HUMAN_OPERATOR = "human_operator"
    HUMAN_REVIEWER = "human_reviewer"
    SYSTEM = "system"


# ─── Substrate-wide classifications ───────────────────────────────


class IntelligenceTraceKind(StrEnum):
    """Trace-call classification (one entry per runtime method).

    The catalogue is pinned by the invariant test.
    """

    SOP_INGEST = "sop_ingest"
    SOP_ANALYZE = "sop_analyze"
    SOP_LIST = "sop_list"
    TONALITY_CLASSIFY = "tonality_classify"
    COMMUNICATION_RETRIEVE = "communication_retrieve"
    COMMUNICATION_REGISTER = "communication_register"
    MEMORY_PROPOSE = "memory_propose"
    MEMORY_APPROVE = "memory_approve"
    MEMORY_REJECT = "memory_reject"
    MEMORY_SUPERSEDE = "memory_supersede"
    MEMORY_RETIRE = "memory_retire"
    MEMORY_LIST = "memory_list"
    PATTERN_ANALYZE = "pattern_analyze"
    RECOMMENDATION_GENERATE = "recommendation_generate"
    RECOMMENDATION_REVIEW = "recommendation_review"
    LOOKUP = "lookup"


class IntelligenceScope(StrEnum):
    """Authority-scope classification of an intelligence artifact."""

    TENANT = "tenant"
    DOMAIN = "domain"
    GLOBAL = "global"


__all__ = [
    "ApprovalAuthorityKind",
    "ApprovalDecision",
    "CommunicationPatternKind",
    "IntelligenceScope",
    "IntelligenceTraceKind",
    "MemoryArtifactKind",
    "MemoryArtifactStatus",
    "OperationalPatternKind",
    "RecommendationKind",
    "RecommendationStatus",
    "RetrievalEligibility",
    "SopFindingKind",
    "SopFindingSeverity",
    "SopStatus",
    "TonalityClass",
    "TonalityIntensity",
]
