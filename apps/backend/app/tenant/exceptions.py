"""Tenant configuration error taxonomy."""

from __future__ import annotations


class TenantConfigurationError(RuntimeError):
    """Base class for tenant configuration failures."""


class TenantConfigurationNotFoundError(TenantConfigurationError):
    """Raised when a tenant-scoped configuration record is absent."""


class TenantConfigurationPersistenceError(TenantConfigurationError):
    """Raised when a tenant configuration write cannot be persisted."""


class TenantCredentialEncryptionError(TenantConfigurationError):
    """Raised when tenant credential encryption cannot proceed safely."""


__all__ = [
    "TenantConfigurationError",
    "TenantConfigurationNotFoundError",
    "TenantConfigurationPersistenceError",
    "TenantCredentialEncryptionError",
]
