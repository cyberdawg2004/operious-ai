"""Typed runtime results for the hardening substrate."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.hardening.enums import (
    ContainmentClassification,
    IntegrityStatus,
    ReplayStatus,
    SurvivabilityStatus,
)
from app.hardening.models.audit import HardeningAudit
from app.hardening.models.containment import (
    SemanticContainmentTrace,
)
from app.hardening.models.dependency import (
    DependencyAuditFinding,
)
from app.hardening.models.failure import (
    FailureContainmentRecord,
)
from app.hardening.models.replay import (
    ReplayEquivalenceFinding,
)
from app.hardening.models.survivability import (
    SurvivabilityFinding,
)
from app.hardening.models.violation import (
    BoundaryViolationFinding,
)


@dataclass(frozen=True, slots=True)
class _BaseResult:
    sequence: int
    runtime_instance_id: uuid.UUID
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ValidateAuthorityOwnershipResult(_BaseResult):
    audit: HardeningAudit | None = None
    containment: SemanticContainmentTrace | None = None
    violations: tuple[BoundaryViolationFinding, ...] = ()


@dataclass(frozen=True, slots=True)
class ValidateLineageResult(_BaseResult):
    audit: HardeningAudit | None = None
    integrity_status: IntegrityStatus | None = None


@dataclass(frozen=True, slots=True)
class ValidateReplayResult(_BaseResult):
    finding: ReplayEquivalenceFinding | None = None


@dataclass(frozen=True, slots=True)
class ValidateReconstructionResult(_BaseResult):
    finding: ReplayEquivalenceFinding | None = None


@dataclass(frozen=True, slots=True)
class ValidateOrderingResult(_BaseResult):
    audit: HardeningAudit | None = None
    integrity_status: IntegrityStatus | None = None


@dataclass(frozen=True, slots=True)
class DetectContaminationResult(_BaseResult):
    audit: HardeningAudit | None = None
    integrity_status: IntegrityStatus | None = None


@dataclass(frozen=True, slots=True)
class AuditDependenciesResult(_BaseResult):
    finding: DependencyAuditFinding | None = None


@dataclass(frozen=True, slots=True)
class ValidateSurvivabilityResult(_BaseResult):
    finding: SurvivabilityFinding | None = None
    survivability_status: SurvivabilityStatus | None = None


@dataclass(frozen=True, slots=True)
class RecordFailureResult(_BaseResult):
    record: FailureContainmentRecord | None = None


@dataclass(frozen=True, slots=True)
class ClassifyContainmentResult(_BaseResult):
    classification: ContainmentClassification | None = None


# ReplayStatus referenced for downstream typing
ReplayStatus  # noqa: B018


__all__ = [
    "AuditDependenciesResult",
    "ClassifyContainmentResult",
    "DetectContaminationResult",
    "RecordFailureResult",
    "ValidateAuthorityOwnershipResult",
    "ValidateLineageResult",
    "ValidateOrderingResult",
    "ValidateReconstructionResult",
    "ValidateReplayResult",
    "ValidateSurvivabilityResult",
]
