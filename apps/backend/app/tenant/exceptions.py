"""Tenant configuration error taxonomy."""

from __future__ import annotations


class TenantConfigurationError(RuntimeError):
    """Base class for tenant configuration failures."""


class TenantConfigurationNotFoundError(TenantConfigurationError):
    """Raised when a tenant-scoped configuration record is absent."""


class TenantConfigurationPersistenceError(TenantConfigurationError):
    """Raised when a tenant configuration write cannot be persisted."""


class ApprovalRequiredError(TenantConfigurationError):
    """Raised when a chronological mutation lacks approved lineage."""


class ChronologyImmutabilityError(TenantConfigurationError):
    """Raised when append-only version history is mutated."""


class TenantTopologyCycleError(TenantConfigurationError):
    """Raised when a tenant topology declaration contains a cycle."""


class TenantCredentialEncryptionError(TenantConfigurationError):
    """Raised when tenant credential encryption cannot proceed safely."""


__all__ = [
    "ApprovalRequiredError",
    "ChronologyImmutabilityError",
    "TenantConfigurationError",
    "TenantConfigurationNotFoundError",
    "TenantConfigurationPersistenceError",
    "TenantCredentialEncryptionError",
    "TenantTopologyCycleError",
]
