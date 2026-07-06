"""Organizational cognition exception hierarchy."""

from __future__ import annotations


class CognitionError(RuntimeError):
    """Base class for cognition runtime failures."""


class CognitionNotFoundError(CognitionError):
    """Raised when a tenant-scoped cognition record is missing."""


class CognitionLifecycleError(CognitionError):
    """Raised when a lifecycle transition is not allowed."""


class CognitionSeparationError(CognitionError):
    """Raised when the approver and proposer are the same principal (dual-control)."""


class CognitionPersistenceError(CognitionError):
    """Raised when cognition persistence collaborators refuse a write."""


class CognitionLLMConfigurationError(CognitionError):
    """Raised when an LLM provider is not configured for live use."""


class CognitionLLMProviderError(CognitionError):
    """Raised when an LLM provider call fails or returns invalid data."""


class ProviderQuotaExceededError(CognitionError):
    """
    Tenant or provider quota exhausted.

    Retryable on diagnostic.retry queue with backoff.
    """

    def __init__(
        self,
        tenant_id: str,
        provider: str,
        model: str,
        quota_type: str,
        retry_after_seconds: int = 60,
    ) -> None:
        self.tenant_id = tenant_id
        self.provider = provider
        self.model = model
        self.quota_type = quota_type
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            "provider quota exhausted: "
            f"{tenant_id}/{provider}/{model}/{quota_type}"
        )


class ProviderRateLimitError(CognitionLLMProviderError):
    """
    Provider returned 429. Retryable with Retry-After respect.

    Maps to error class PROVIDER_429.
    """

    retry_after_seconds: int

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: int = 60,
    ) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)


class ProviderTransientError(CognitionLLMProviderError):
    """
    Provider returned 5xx. Retryable with exponential backoff.

    Maps to error class PROVIDER_5XX.
    """


class CognitionSemanticValidationError(CognitionError):
    """Raised when model output drifts governance-significant meaning."""


class CognitionParsingFailureError(CognitionSemanticValidationError):
    """
    LLM output failed DiagnosticLLMOutput schema validation.

    Retryable once with tightened prompt. Then DLQ.
    Maps to error class PARSING_FAILURE.
    """


class CognitionSemanticRejectionError(CognitionSemanticValidationError):
    """
    Valid JSON but category fails semantic validation.

    Not retryable - semantic issue will not resolve.
    Goes directly to DLQ.
    Maps to error class SEMANTIC_REJECTION.
    """


class CognitionGovernanceRejectionError(CognitionError):
    """Raised when governance rejects model output before completion."""


class GovernanceDenyError(CognitionError):
    """
    Governance denied the proposed action.

    Not retryable - deterministic decision.
    Goes directly to DLQ.
    Maps to error class GOVERNANCE_DENY.
    """


class CognitionPersistenceFailureError(CognitionError):
    """
    DB write failed after successful LLM cognition.

    Retryable - DB may recover.
    Maps to error class PERSISTENCE_FAILURE.
    """


__all__ = [
    "CognitionError",
    "CognitionGovernanceRejectionError",
    "CognitionLLMConfigurationError",
    "CognitionLLMProviderError",
    "CognitionLifecycleError",
    "CognitionNotFoundError",
    "CognitionSeparationError",
    "CognitionParsingFailureError",
    "CognitionPersistenceError",
    "CognitionPersistenceFailureError",
    "CognitionSemanticRejectionError",
    "CognitionSemanticValidationError",
    "GovernanceDenyError",
    "ProviderQuotaExceededError",
    "ProviderRateLimitError",
    "ProviderTransientError",
]
