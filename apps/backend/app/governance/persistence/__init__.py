"""Governance persistence foundation — storage-agnostic contracts.

Sprint I Hardening ships the **canonical persistence contracts**.
This package defines:

* `records`       — frozen, serializable, query-oriented record
                    shapes (one per durable governance artefact).
* `serializers`   — pure functions that convert runtime types
                    (`GovernanceDecision`, `GovernanceTrace`, etc.)
                    into the record shapes and back.
* `repository`    — `BaseGovernanceRepository` Protocol — the
                    storage-agnostic contract every backend honours.
* `models`        — query parameter + result-page shapes.
* `memory`        — `InMemoryGovernanceRepository`: the reference
                    implementation used by tests and dev environments.

Architectural rules:

* **NO ORM coupling.** Records are plain frozen dataclasses with
  `to_dict` / `from_dict`. SQLAlchemy, Alembic, etc. land in a
  later sprint behind the same Protocol.
* **NO direct import of runtime types in records.** Records are
  reference-by-value; they carry IDs and serialised structures, not
  live runtime objects.
* **Storage backends are pluggable.** Adding Postgres, S3, or any
  other store is a new module that implements `BaseGovernanceRepository`.
  The substrate is untouched.
"""

from app.governance.persistence.memory import InMemoryGovernanceRepository
from app.governance.persistence.models import DecisionQuery, RecordPage
from app.governance.persistence.records import (
    EnforcementActionRecord,
    GovernanceDecisionRecord,
    GovernanceTraceRecord,
    PolicyEvaluationResultRecord,
    PolicyEvaluationTraceRecord,
    PolicyViolationRecord,
    RuntimeRestrictionRecord,
)
from app.governance.persistence.repository import BaseGovernanceRepository
from app.governance.persistence.serializers import (
    decision_to_record,
    enforcement_action_to_record,
    record_to_decision,
    trace_to_record,
)

__all__ = [
    # Records
    "GovernanceDecisionRecord",
    "GovernanceTraceRecord",
    "PolicyEvaluationResultRecord",
    "PolicyEvaluationTraceRecord",
    "EnforcementActionRecord",
    "PolicyViolationRecord",
    "RuntimeRestrictionRecord",
    # Models
    "DecisionQuery",
    "RecordPage",
    # Serializers
    "decision_to_record",
    "record_to_decision",
    "trace_to_record",
    "enforcement_action_to_record",
    # Repositories
    "BaseGovernanceRepository",
    "InMemoryGovernanceRepository",
]
