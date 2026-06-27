"""Tenant configuration error taxonomy."""

from __future__ import annotations


class TenantConfigurationError(RuntimeError):
    """Base class for tenant configuration failures."""


class TenantConfigurationNotFoundError(TenantConfigurationError):
    """Raised when a tenant-scoped configuration record is absent."""


class TenantConfigurationPersistenceError(TenantConfigurationError):
    """Raised when a tenant configuration write cannot be persisted."""


class TenantConfigurationDirectApplyDisabledError(TenantConfigurationError):
    """Raised when legacy direct configuration mutation is disabled."""


class TenantConfigurationDualControlRequiredError(TenantConfigurationError):
    """Raised when a direct apply targets a safety-relevant policy_type.

    Distinct from :class:`TenantConfigurationDirectApplyDisabledError`,
    which is an environment-flag gate (disabled in production, opt-in
    elsewhere). This error is structural and policy_type-scoped: it fires
    regardless of ``tenant_config_self_approval_allowed`` so a safety-
    relevant policy can never be mutated outside the change-request
    ledger, even in an environment where legacy direct apply is enabled.
    """


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
    "TenantConfigurationDirectApplyDisabledError",
    "TenantConfigurationDualControlRequiredError",
    "TenantConfigurationError",
    "TenantConfigurationNotFoundError",
    "TenantConfigurationPersistenceError",
    "TenantCredentialEncryptionError",
    "TenantTopologyCycleError",
]
