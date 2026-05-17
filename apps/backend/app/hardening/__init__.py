"""Operious AI — hardening substrate.

The hardening substrate detects, validates, audits, and
classifies. It NEVER mutates runtime behaviour. Its discipline
is observational by design — see PART 1 of the hardening sprint
brief for the architectural contract.
"""

from app.hardening.contracts.requests import (
    AuditDependenciesRequest,
    ClassifyContainmentRequest,
    DetectContaminationRequest,
    RecordFailureRequest,
    ValidateAuthorityOwnershipRequest,
    ValidateLineageRequest,
    ValidateOrderingRequest,
    ValidateReconstructionRequest,
    ValidateReplayRequest,
    ValidateSurvivabilityRequest,
)
from app.hardening.contracts.results import (
    AuditDependenciesResult,
    ClassifyContainmentResult,
    DetectContaminationResult,
    RecordFailureResult,
    ValidateAuthorityOwnershipResult,
    ValidateLineageResult,
    ValidateOrderingResult,
    ValidateReconstructionResult,
    ValidateReplayResult,
    ValidateSurvivabilityResult,
)
from app.hardening.enums import (
    ContainmentClassification,
    FailureClassification,
    HardeningFindingKind,
    HardeningSeverity,
    HardeningStatus,
    HardeningTraceKind,
    IntegrityStatus,
    ReplayStatus,
    SubstrateName,
    SurvivabilityStatus,
)
from app.hardening.envelopes import HardeningEnvelope
from app.hardening.exceptions import (
    HardeningConfigurationError,
    HardeningContainmentError,
    HardeningError,
    HardeningInvariantError,
    HardeningNotFoundError,
    HardeningPersistenceError,
    HardeningValidationError,
)
from app.hardening.identity import (
    BoundaryViolationId,
    DependencyAuditId,
    FailureContainmentRecordId,
    HardeningAuditId,
    HardeningCorrelationId,
    HardeningFindingId,
    HardeningTraceId,
    SemanticAuthorityBoundaryId,
)
from app.hardening.models import (
    AuthorityOwnershipMap,
    BoundaryViolationFinding,
    DependencyAuditFinding,
    DependencyEdge,
    FailureContainmentRecord,
    HardeningAudit,
    HardeningFinding,
    ReplayEquivalenceFinding,
    SemanticAuthorityBoundary,
    SemanticContainmentTrace,
    SurvivabilityFinding,
)
from app.hardening.models.ownership import (
    CANONICAL_AUTHORITY_OWNERSHIP_MAP,
)
from app.hardening.persistence import (
    HardeningPersistenceProtocol,
    InMemoryHardeningPersistence,
)
from app.hardening.semantic import (
    OwnershipInvariantValidator,
)
from app.hardening.taxonomy import HardeningMetadataKey
from app.hardening.traces import (
    HardeningTrace,
    HardeningTraceContext,
)
from app.hardening.validation import HardeningRuntime

__all__ = [
    "AuditDependenciesRequest",
    "AuditDependenciesResult",
    "AuthorityOwnershipMap",
    "BoundaryViolationFinding",
    "BoundaryViolationId",
    "CANONICAL_AUTHORITY_OWNERSHIP_MAP",
    "ClassifyContainmentRequest",
    "ClassifyContainmentResult",
    "ContainmentClassification",
    "DependencyAuditFinding",
    "DependencyAuditId",
    "DependencyEdge",
    "DetectContaminationRequest",
    "DetectContaminationResult",
    "FailureClassification",
    "FailureContainmentRecord",
    "FailureContainmentRecordId",
    "HardeningAudit",
    "HardeningAuditId",
    "HardeningConfigurationError",
    "HardeningContainmentError",
    "HardeningCorrelationId",
    "HardeningEnvelope",
    "HardeningError",
    "HardeningFinding",
    "HardeningFindingId",
    "HardeningFindingKind",
    "HardeningInvariantError",
    "HardeningMetadataKey",
    "HardeningNotFoundError",
    "HardeningPersistenceError",
    "HardeningPersistenceProtocol",
    "HardeningRuntime",
    "HardeningSeverity",
    "HardeningStatus",
    "HardeningTrace",
    "HardeningTraceContext",
    "HardeningTraceId",
    "HardeningTraceKind",
    "HardeningValidationError",
    "InMemoryHardeningPersistence",
    "IntegrityStatus",
    "OwnershipInvariantValidator",
    "RecordFailureRequest",
    "RecordFailureResult",
    "ReplayEquivalenceFinding",
    "ReplayStatus",
    "SemanticAuthorityBoundary",
    "SemanticAuthorityBoundaryId",
    "SemanticContainmentTrace",
    "SubstrateName",
    "SurvivabilityFinding",
    "SurvivabilityStatus",
    "ValidateAuthorityOwnershipRequest",
    "ValidateAuthorityOwnershipResult",
    "ValidateLineageRequest",
    "ValidateLineageResult",
    "ValidateOrderingRequest",
    "ValidateOrderingResult",
    "ValidateReconstructionRequest",
    "ValidateReconstructionResult",
    "ValidateReplayRequest",
    "ValidateReplayResult",
    "ValidateSurvivabilityRequest",
    "ValidateSurvivabilityResult",
]
