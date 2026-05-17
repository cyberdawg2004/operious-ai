"""Operious AI — multilingual boundary substrate.

Translate at the edge. Reason in the core. The core operational
cognition layer remains canonical-English only. The translation
substrate translates representation; it MUST NEVER alter
governance, escalation, authority, compliance, or SOP semantics.
"""

from app.boundary.translation.contracts.requests import (
    EgressLocalizeRequest,
    IngressTranslateRequest,
)
from app.boundary.translation.contracts.results import (
    EgressLocalizeResult,
    IngressTranslateResult,
)
from app.boundary.translation.egress.runtime import (
    TranslationEgressRuntime,
)
from app.boundary.translation.enums import (
    CANONICAL_LANGUAGE,
    LocalizationFormality,
    SemanticPreservationStatus,
    TranslationDirection,
    TranslationFindingKind,
    TranslationProviderKind,
    TranslationStatus,
    TranslationTraceKind,
)
from app.boundary.translation.envelopes import (
    TranslationEnvelope,
)
from app.boundary.translation.exceptions import (
    TranslationConfigurationError,
    TranslationContainmentError,
    TranslationError,
    TranslationNotFoundError,
    TranslationPersistenceError,
    TranslationProviderError,
    TranslationValidationError,
)
from app.boundary.translation.identity import (
    LocalizationId,
    TranslationCorrelationId,
    TranslationId,
    TranslationLineageId,
    TranslationProviderId,
    TranslationReplayId,
    TranslationTraceId,
)
from app.boundary.translation.ingress.runtime import (
    TranslationIngressRuntime,
)
from app.boundary.translation.localization.context import (
    LocalizationContext,
    derive_formality,
)
from app.boundary.translation.models import (
    CanonicalLanguageProjection,
    LocalizationMetadata,
    SemanticPreservationCheck,
    TranslationIdentity,
    TranslationLineage,
    TranslationNormalization,
    TranslationPayload,
    TranslationReplay,
    TranslationValidation,
)
from app.boundary.translation.models.validation import (
    TranslationFinding,
)
from app.boundary.translation.normalization.normalizer import (
    BoundaryNormalizer,
)
from app.boundary.translation.persistence import (
    EgressLocalizationRecord,
    InMemoryTranslationPersistence,
    IngressTranslationRecord,
    TranslationPersistenceProtocol,
)
from app.boundary.translation.providers import (
    BaseTranslationProvider,
    IdentityTranslationProvider,
    TranslationProviderRequest,
    TranslationProviderResponse,
)
from app.boundary.translation.replay.verifier import (
    verify_translation_replay,
)
from app.boundary.translation.runtime.aggregator import (
    TranslationRuntime,
)
from app.boundary.translation.semantic_validation.validator import (
    GOVERNANCE_KEYWORDS,
    SemanticPreservationValidator,
)
from app.boundary.translation.traces import (
    TranslationTrace,
    TranslationTraceContext,
)

__all__ = [
    "BaseTranslationProvider",
    "BoundaryNormalizer",
    "CANONICAL_LANGUAGE",
    "CanonicalLanguageProjection",
    "EgressLocalizationRecord",
    "EgressLocalizeRequest",
    "EgressLocalizeResult",
    "GOVERNANCE_KEYWORDS",
    "IdentityTranslationProvider",
    "InMemoryTranslationPersistence",
    "IngressTranslateRequest",
    "IngressTranslateResult",
    "IngressTranslationRecord",
    "LocalizationContext",
    "LocalizationFormality",
    "LocalizationId",
    "LocalizationMetadata",
    "SemanticPreservationCheck",
    "SemanticPreservationStatus",
    "SemanticPreservationValidator",
    "TranslationConfigurationError",
    "TranslationContainmentError",
    "TranslationCorrelationId",
    "TranslationDirection",
    "TranslationEgressRuntime",
    "TranslationEnvelope",
    "TranslationError",
    "TranslationFinding",
    "TranslationFindingKind",
    "TranslationId",
    "TranslationIdentity",
    "TranslationIngressRuntime",
    "TranslationLineage",
    "TranslationLineageId",
    "TranslationNormalization",
    "TranslationNotFoundError",
    "TranslationPayload",
    "TranslationPersistenceError",
    "TranslationPersistenceProtocol",
    "TranslationProviderError",
    "TranslationProviderId",
    "TranslationProviderKind",
    "TranslationProviderRequest",
    "TranslationProviderResponse",
    "TranslationReplay",
    "TranslationReplayId",
    "TranslationRuntime",
    "TranslationStatus",
    "TranslationTrace",
    "TranslationTraceContext",
    "TranslationTraceId",
    "TranslationTraceKind",
    "TranslationValidation",
    "TranslationValidationError",
    "derive_formality",
    "verify_translation_replay",
]
