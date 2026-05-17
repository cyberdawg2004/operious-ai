"""Hardening-substrate identity primitives.

Eight typed identifiers, all deterministically derivable via
UUID5 from a stable seed. Permanent namespace constants pin
every deriver — changing one is a breaking change.
"""

from __future__ import annotations

import uuid
from typing import NewType


# ─── Type aliases ───────────────────────────────────────────────────


HardeningAuditId = NewType("HardeningAuditId", uuid.UUID)
HardeningFindingId = NewType("HardeningFindingId", uuid.UUID)
HardeningTraceId = NewType("HardeningTraceId", uuid.UUID)
HardeningCorrelationId = NewType(
    "HardeningCorrelationId", uuid.UUID
)
SemanticAuthorityBoundaryId = NewType(
    "SemanticAuthorityBoundaryId", uuid.UUID
)
BoundaryViolationId = NewType("BoundaryViolationId", uuid.UUID)
FailureContainmentRecordId = NewType(
    "FailureContainmentRecordId", uuid.UUID
)
DependencyAuditId = NewType("DependencyAuditId", uuid.UUID)


# ─── Permanent namespace constants ──────────────────────────────────


_AUDIT_NAMESPACE = uuid.UUID(
    "01087ec0-0001-4001-8001-000000000001"
)
_FINDING_NAMESPACE = uuid.UUID(
    "01087ec0-0002-4002-8002-000000000002"
)
_TRACE_NAMESPACE = uuid.UUID(
    "01087ec0-0003-4003-8003-000000000003"
)
_CORRELATION_NAMESPACE = uuid.UUID(
    "01087ec0-0004-4004-8004-000000000004"
)
_BOUNDARY_NAMESPACE = uuid.UUID(
    "01087ec0-0005-4005-8005-000000000005"
)
_VIOLATION_NAMESPACE = uuid.UUID(
    "01087ec0-0006-4006-8006-000000000006"
)
_FAILURE_NAMESPACE = uuid.UUID(
    "01087ec0-0007-4007-8007-000000000007"
)
_DEPENDENCY_NAMESPACE = uuid.UUID(
    "01087ec0-0008-4008-8008-000000000008"
)


# ─── Generators (UUID4) ─────────────────────────────────────────────


def generate_audit_id() -> HardeningAuditId:
    return HardeningAuditId(uuid.uuid4())


def generate_finding_id() -> HardeningFindingId:
    return HardeningFindingId(uuid.uuid4())


def generate_trace_id() -> HardeningTraceId:
    return HardeningTraceId(uuid.uuid4())


def generate_correlation_id() -> HardeningCorrelationId:
    return HardeningCorrelationId(uuid.uuid4())


def generate_boundary_id() -> SemanticAuthorityBoundaryId:
    return SemanticAuthorityBoundaryId(uuid.uuid4())


def generate_violation_id() -> BoundaryViolationId:
    return BoundaryViolationId(uuid.uuid4())


def generate_failure_record_id() -> FailureContainmentRecordId:
    return FailureContainmentRecordId(uuid.uuid4())


def generate_dependency_audit_id() -> DependencyAuditId:
    return DependencyAuditId(uuid.uuid4())


# ─── Replay-safe deterministic UUID5 derivers ───────────────────────


def derive_audit_id(*, seed: str) -> HardeningAuditId:
    if not seed:
        raise ValueError("derive_audit_id requires seed")
    return HardeningAuditId(uuid.uuid5(_AUDIT_NAMESPACE, seed))


def derive_finding_id(
    *,
    audit_seed: str,
    kind: str,
    ordinal: int,
) -> HardeningFindingId:
    return HardeningFindingId(
        uuid.uuid5(
            _FINDING_NAMESPACE,
            f"{audit_seed}|{kind}|{ordinal}",
        )
    )


def derive_trace_id(*, seed: str) -> HardeningTraceId:
    if not seed:
        raise ValueError("derive_trace_id requires seed")
    return HardeningTraceId(uuid.uuid5(_TRACE_NAMESPACE, seed))


def derive_correlation_id(
    *, seed: str
) -> HardeningCorrelationId:
    if not seed:
        raise ValueError("derive_correlation_id requires seed")
    return HardeningCorrelationId(
        uuid.uuid5(_CORRELATION_NAMESPACE, seed)
    )


def derive_boundary_id(
    *, concern: str, owner: str
) -> SemanticAuthorityBoundaryId:
    if not concern or not owner:
        raise ValueError(
            "derive_boundary_id requires concern + owner"
        )
    return SemanticAuthorityBoundaryId(
        uuid.uuid5(_BOUNDARY_NAMESPACE, f"{concern}|{owner}")
    )


def derive_violation_id(
    *,
    boundary_concern: str,
    offender: str,
    detail: str,
) -> BoundaryViolationId:
    return BoundaryViolationId(
        uuid.uuid5(
            _VIOLATION_NAMESPACE,
            f"{boundary_concern}|{offender}|{detail}",
        )
    )


def derive_failure_record_id(
    *, seed: str
) -> FailureContainmentRecordId:
    if not seed:
        raise ValueError("derive_failure_record_id requires seed")
    return FailureContainmentRecordId(
        uuid.uuid5(_FAILURE_NAMESPACE, seed)
    )


def derive_dependency_audit_id(
    *, seed: str
) -> DependencyAuditId:
    if not seed:
        raise ValueError(
            "derive_dependency_audit_id requires seed"
        )
    return DependencyAuditId(
        uuid.uuid5(_DEPENDENCY_NAMESPACE, seed)
    )


__all__ = [
    "BoundaryViolationId",
    "DependencyAuditId",
    "FailureContainmentRecordId",
    "HardeningAuditId",
    "HardeningCorrelationId",
    "HardeningFindingId",
    "HardeningTraceId",
    "SemanticAuthorityBoundaryId",
    "derive_audit_id",
    "derive_boundary_id",
    "derive_correlation_id",
    "derive_dependency_audit_id",
    "derive_failure_record_id",
    "derive_finding_id",
    "derive_trace_id",
    "derive_violation_id",
    "generate_audit_id",
    "generate_boundary_id",
    "generate_correlation_id",
    "generate_dependency_audit_id",
    "generate_failure_record_id",
    "generate_finding_id",
    "generate_trace_id",
    "generate_violation_id",
]
