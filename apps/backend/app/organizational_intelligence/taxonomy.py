"""Canonical metadata-key vocabulary for the intelligence substrate.

All keys are namespaced ``intelligence.*`` so they never collide
with sibling-substrate (``coordination.*`` / ``boundary.*`` /
``session.*`` / ``arbitration.*`` / ``coordination.policy.*`` /
``coordination.topology.*``) metadata.
"""

from __future__ import annotations

from enum import StrEnum


class IntelligenceMetadataKey(StrEnum):
    SOP_ID = "intelligence.sop_id"
    SOP_VERSION = "intelligence.sop_version"
    SOP_STATUS = "intelligence.sop_status"
    FINDING_ID = "intelligence.finding_id"
    FINDING_KIND = "intelligence.finding_kind"
    FINDING_SEVERITY = "intelligence.finding_severity"
    TONALITY_CLASS = "intelligence.tonality_class"
    TONALITY_INTENSITY = "intelligence.tonality_intensity"
    COMMUNICATION_PATTERN_ID = (
        "intelligence.communication_pattern_id"
    )
    COMMUNICATION_PATTERN_KIND = (
        "intelligence.communication_pattern_kind"
    )
    ARTIFACT_ID = "intelligence.artifact_id"
    ARTIFACT_KIND = "intelligence.artifact_kind"
    ARTIFACT_STATUS = "intelligence.artifact_status"
    CANDIDATE_PATTERN_ID = "intelligence.candidate_pattern_id"
    APPROVED_PATTERN_ID = "intelligence.approved_pattern_id"
    PROPOSAL_ID = "intelligence.proposal_id"
    LINEAGE_ID = "intelligence.lineage_id"
    APPROVAL_ID = "intelligence.approval_id"
    APPROVAL_DECISION = "intelligence.approval_decision"
    APPROVER_HANDLE = "intelligence.approver_handle"
    PATTERN_OBSERVATION_ID = (
        "intelligence.pattern_observation_id"
    )
    PATTERN_ANALYSIS_ID = "intelligence.pattern_analysis_id"
    PATTERN_KIND = "intelligence.pattern_kind"
    RECOMMENDATION_ID = "intelligence.recommendation_id"
    RECOMMENDATION_KIND = "intelligence.recommendation_kind"
    RECOMMENDATION_STATUS = "intelligence.recommendation_status"
    RETRIEVAL_ELIGIBILITY = "intelligence.retrieval_eligibility"
    SOURCE_SESSION_ID = "intelligence.source_session_id"
    SOURCE_BOUNDARY_EVENT_ID = (
        "intelligence.source_boundary_event_id"
    )
    SOURCE_SUPERVISOR_EVALUATION_ID = (
        "intelligence.source_supervisor_evaluation_id"
    )
    SOURCE_GOVERNANCE_EVALUATION_ID = (
        "intelligence.source_governance_evaluation_id"
    )
    TENANT_ID = "intelligence.tenant_id"
    SCOPE = "intelligence.scope"
    CONTENT_FINGERPRINT = "intelligence.content_fingerprint"


__all__ = ["IntelligenceMetadataKey"]
