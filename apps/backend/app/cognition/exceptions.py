"""Organizational cognition exception hierarchy."""

from __future__ import annotations


class CognitionError(RuntimeError):
    """Base class for cognition runtime failures."""


class CognitionNotFoundError(CognitionError):
    """Raised when a tenant-scoped cognition record is missing."""


class CognitionLifecycleError(CognitionError):
    """Raised when a lifecycle transition is not allowed."""


class CognitionPersistenceError(CognitionError):
    """Raised when cognition persistence collaborators refuse a write."""


class CognitionLLMConfigurationError(CognitionError):
    """Raised when an LLM provider is not configured for live use."""


class CognitionLLMProviderError(CognitionError):
    """Raised when an LLM provider call fails or returns invalid data."""


class CognitionSemanticValidationError(CognitionError):
    """Raised when model output drifts governance-significant meaning."""


class CognitionGovernanceRejectionError(CognitionError):
    """Raised when governance rejects model output before completion."""


__all__ = [
    "CognitionError",
    "CognitionGovernanceRejectionError",
    "CognitionLLMConfigurationError",
    "CognitionLLMProviderError",
    "CognitionLifecycleError",
    "CognitionNotFoundError",
    "CognitionPersistenceError",
    "CognitionSemanticValidationError",
]
