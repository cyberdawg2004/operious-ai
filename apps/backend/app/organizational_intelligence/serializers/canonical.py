"""Pure canonical serialisation + content-fingerprinting helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Mapping

from app.organizational_intelligence.models.approval import (
    ApprovalRecord,
)
from app.organizational_intelligence.models.communication import (
    CommunicationPattern,
)
from app.organizational_intelligence.models.memory import (
    ApprovedPattern,
    CandidatePattern,
    OrganizationalMemoryArtifact,
)
from app.organizational_intelligence.models.recommendation import (
    OrganizationalRecommendation,
)
from app.organizational_intelligence.models.sop import (
    SopAnalysis,
    SopFinding,
    StandardOperatingProcedure,
)
from app.organizational_intelligence.models.tonality import (
    TonalityAnalysis,
)


_PRIMITIVES = (str, int, float, bool, type(None))


def canonicalize_payload(value: Any) -> Any:
    """Recursively normalise into a canonical JSON-safe shape."""
    if isinstance(value, Mapping):
        return {
            key: canonicalize_payload(value[key])
            for key in sorted(value.keys(), key=_string_key)
        }
    if isinstance(value, (list, tuple)):
        return [canonicalize_payload(i) for i in value]
    if isinstance(value, set):
        sorted_items = sorted(
            value,
            key=lambda x: json.dumps(
                canonicalize_payload(x), default=str
            ),
        )
        return [canonicalize_payload(i) for i in sorted_items]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, _PRIMITIVES):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def canonicalize_attributes(
    attributes: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]
        attributes, Mapping
    ):
        raise TypeError(
            f"canonicalize_attributes expected a Mapping, got "
            f"{type(attributes).__name__!r}"
        )
    return {
        key: canonicalize_payload(attributes[key])
        for key in sorted(attributes.keys(), key=_string_key)
    }


def content_fingerprint(value: Any) -> str:
    """Stable SHA-256 hex digest over canonical JSON encoding."""
    canonical = canonicalize_payload(value)
    blob = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ─── Apex projection helpers ────────────────────────────────────────


def serialize_sop(
    sop: StandardOperatingProcedure,
) -> dict[str, Any]:
    return canonicalize_payload(
        {
            "sop_id": str(sop.sop_id),
            "tenant_id": sop.tenant_id,
            "scope": sop.scope.value,
            "external_handle": sop.external_handle,
            "status": sop.status.value,
            "current_version": {
                "version_id": str(sop.current_version.version_id),
                "version": sop.current_version.version,
                "title": sop.current_version.title,
                "body": sop.current_version.body,
                "content_fingerprint": (
                    sop.current_version.content_fingerprint
                ),
                "ingested_at": sop.current_version.ingested_at,
                "author_handle": (
                    sop.current_version.author_handle
                ),
            },
            "ingested_at": sop.ingested_at,
            "last_updated_at": sop.last_updated_at,
            "version_history": [
                str(v) for v in sop.version_history
            ],
            "revision": sop.revision,
        }
    )


def serialize_sop_finding(finding: SopFinding) -> dict[str, Any]:
    return canonicalize_payload(
        {
            "finding_id": str(finding.finding_id),
            "sop_id": str(finding.sop_id),
            "sop_version": finding.sop_version,
            "ordinal": finding.ordinal,
            "kind": finding.kind.value,
            "severity": finding.severity.value,
            "summary": finding.summary,
            "location_hint": finding.location_hint,
            "evidence": list(finding.evidence),
            "detected_at": finding.detected_at,
        }
    )


def serialize_sop_analysis(analysis: SopAnalysis) -> dict[str, Any]:
    return canonicalize_payload(
        {
            "analysis_id": str(analysis.analysis_id),
            "sop_id": str(analysis.sop_id),
            "sop_version": analysis.sop_version,
            "analyzer_signature": analysis.analyzer_signature,
            "analyzed_at": analysis.analyzed_at,
            "summary": analysis.summary,
            "findings": [
                serialize_sop_finding(f) for f in analysis.findings
            ],
        }
    )


def serialize_tonality_analysis(
    analysis: TonalityAnalysis,
) -> dict[str, Any]:
    return canonicalize_payload(
        {
            "analysis_id": str(analysis.analysis_id),
            "content_fingerprint": analysis.content_fingerprint,
            "analyzer_signature": analysis.analyzer_signature,
            "analyzed_at": analysis.analyzed_at,
            "primary_tag": {
                "class": analysis.primary_tag.tonality_class.value,
                "intensity": analysis.primary_tag.intensity.value,
                "confidence": analysis.primary_tag.confidence,
            },
            "tags": [
                {
                    "class": t.tonality_class.value,
                    "intensity": t.intensity.value,
                    "confidence": t.confidence,
                    "evidence": list(t.evidence),
                }
                for t in analysis.tags
            ],
            "tenant_id": analysis.tenant_id,
            "correlation_hint": analysis.correlation_hint,
        }
    )


def serialize_communication_pattern(
    pattern: CommunicationPattern,
) -> dict[str, Any]:
    return canonicalize_payload(
        {
            "pattern_id": str(pattern.pattern_id),
            "tenant_id": pattern.tenant_id,
            "scope": pattern.scope.value,
            "kind": pattern.kind.value,
            "handle": pattern.handle,
            "body": pattern.body,
            "applicable_classes": [
                c.value for c in pattern.applicable_classes
            ],
            "approval_id": str(pattern.approval_id),
            "registered_at": pattern.registered_at,
            "author_handle": pattern.author_handle,
        }
    )


def serialize_candidate(
    candidate: CandidatePattern,
) -> dict[str, Any]:
    return canonicalize_payload(
        {
            "candidate_id": str(candidate.candidate_id),
            "observation_seed": candidate.observation_seed,
            "kind": candidate.kind.value,
            "summary": candidate.summary,
            "body": candidate.body,
            "content_fingerprint": (
                candidate.content_fingerprint
            ),
            "evidence": list(candidate.evidence),
            "extracted_at": candidate.extracted_at,
            "extractor_signature": (
                candidate.extractor_signature
            ),
            "scope": candidate.scope.value,
            "tenant_id": candidate.tenant_id,
        }
    )


def serialize_approved_pattern(
    pattern: ApprovedPattern,
) -> dict[str, Any]:
    return canonicalize_payload(
        {
            "approved_pattern_id": str(
                pattern.approved_pattern_id
            ),
            "candidate_id": str(pattern.candidate_id),
            "approval_id": str(pattern.approval_id),
            "approved_at": pattern.approved_at,
            "kind": pattern.kind.value,
            "scope": pattern.scope.value,
            "tenant_id": pattern.tenant_id,
            "approver_handle": pattern.approver_handle,
            "body": pattern.body,
        }
    )


def serialize_memory_artifact(
    artifact: OrganizationalMemoryArtifact,
) -> dict[str, Any]:
    return canonicalize_payload(
        {
            "artifact_id": str(artifact.artifact_id),
            "kind": artifact.kind.value,
            "scope": artifact.scope.value,
            "tenant_id": artifact.tenant_id,
            "status": artifact.status.value,
            "body": artifact.body,
            "content_fingerprint": artifact.content_fingerprint,
            "candidate_id": (
                str(artifact.candidate_id)
                if artifact.candidate_id is not None
                else None
            ),
            "approved_pattern_id": (
                str(artifact.approved_pattern_id)
                if artifact.approved_pattern_id is not None
                else None
            ),
            "approval_id": (
                str(artifact.approval_id)
                if artifact.approval_id is not None
                else None
            ),
            "proposal_id": (
                str(artifact.proposal_id)
                if artifact.proposal_id is not None
                else None
            ),
            "lineage": {
                "lineage_id": str(artifact.lineage.lineage_id),
                "root_artifact_id": str(
                    artifact.lineage.root_artifact_id
                ),
                "parent_artifact_id": (
                    str(artifact.lineage.parent_artifact_id)
                    if artifact.lineage.parent_artifact_id is not None
                    else None
                ),
                "ancestor_artifact_ids": [
                    str(a)
                    for a in artifact.lineage.ancestor_artifact_ids
                ],
                "depth": artifact.lineage.depth,
            },
            "eligibility": artifact.eligibility.value,
            "created_at": artifact.created_at,
            "updated_at": artifact.updated_at,
            "revision": artifact.revision,
            "superseded_by": (
                str(artifact.superseded_by)
                if artifact.superseded_by is not None
                else None
            ),
        }
    )


def serialize_recommendation(
    recommendation: OrganizationalRecommendation,
) -> dict[str, Any]:
    return canonicalize_payload(
        {
            "recommendation_id": str(
                recommendation.recommendation_id
            ),
            "kind": recommendation.kind.value,
            "scope": recommendation.scope.value,
            "tenant_id": recommendation.tenant_id,
            "status": recommendation.status.value,
            "title": recommendation.title,
            "body": recommendation.body,
            "target_handle": recommendation.target_handle,
            "rationale": {
                "summary": recommendation.rationale.summary,
                "evidence": list(
                    recommendation.rationale.evidence
                ),
                "related_finding_ids": list(
                    recommendation.rationale.related_finding_ids
                ),
                "related_pattern_ids": list(
                    recommendation.rationale.related_pattern_ids
                ),
            },
            "proposed_at": recommendation.proposed_at,
            "reviewed_at": recommendation.reviewed_at,
            "approval_id": (
                str(recommendation.approval_id)
                if recommendation.approval_id is not None
                else None
            ),
            "superseded_by": (
                str(recommendation.superseded_by)
                if recommendation.superseded_by is not None
                else None
            ),
            "revision": recommendation.revision,
        }
    )


def serialize_approval(approval: ApprovalRecord) -> dict[str, Any]:
    return canonicalize_payload(
        {
            "approval_id": str(approval.approval_id),
            "target_id": str(approval.target_id),
            "target_kind": approval.target_kind,
            "decision": approval.decision.value,
            "authority": approval.authority.value,
            "approver_handle": approval.approver_handle,
            "decided_at": approval.decided_at,
            "rationale": approval.rationale,
            "attributes": dict(approval.attributes),
        }
    )


def _string_key(key: Any) -> str:
    return (
        key
        if isinstance(key, str)
        else json.dumps(key, default=str, sort_keys=True)
    )


__all__ = [
    "canonicalize_attributes",
    "canonicalize_payload",
    "content_fingerprint",
    "serialize_approval",
    "serialize_approved_pattern",
    "serialize_candidate",
    "serialize_communication_pattern",
    "serialize_memory_artifact",
    "serialize_recommendation",
    "serialize_sop",
    "serialize_sop_analysis",
    "serialize_sop_finding",
    "serialize_tonality_analysis",
]
