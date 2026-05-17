"""Canonical metadata-key vocabulary for the hardening substrate."""

from __future__ import annotations

from enum import StrEnum


class HardeningMetadataKey(StrEnum):
    AUDIT_ID = "hardening.audit_id"
    FINDING_ID = "hardening.finding_id"
    BOUNDARY_ID = "hardening.boundary_id"
    VIOLATION_ID = "hardening.violation_id"
    FAILURE_RECORD_ID = "hardening.failure_record_id"
    DEPENDENCY_AUDIT_ID = "hardening.dependency_audit_id"
    SUBSTRATE = "hardening.substrate"
    CONCERN = "hardening.concern"
    OWNER = "hardening.owner"
    OFFENDER = "hardening.offender"
    SEVERITY = "hardening.severity"
    KIND = "hardening.kind"
    SCOPE = "hardening.scope"
    REPLAY_STATUS = "hardening.replay_status"
    SURVIVABILITY_STATUS = "hardening.survivability_status"
    INTEGRITY_STATUS = "hardening.integrity_status"
    CONTAINMENT_CLASSIFICATION = (
        "hardening.containment_classification"
    )
    FAILURE_CLASSIFICATION = (
        "hardening.failure_classification"
    )
    SOURCE_FINGERPRINT = "hardening.source_fingerprint"
    CANDIDATE_FINGERPRINT = "hardening.candidate_fingerprint"


__all__ = ["HardeningMetadataKey"]
