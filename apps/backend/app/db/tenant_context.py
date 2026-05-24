"""Tenant session context for PostgreSQL RLS.

This module provides the mechanism to set app.current_tenant_id as a
PostgreSQL session variable before each transaction, enabling FORCE ROW
LEVEL SECURITY to enforce tenant isolation at the database level.

The ContextVar is async-safe: each asyncio task has its own value.
Transaction-local setting is pool-safe: it resets when the transaction
ends, preventing cross-tenant contamination in connection pools.
"""

from __future__ import annotations

import sys
from contextvars import ContextVar
from typing import Optional

_CANONICAL_MODULE = "app.db.tenant_context"
_COMPAT_MODULE = "apps.backend.app.db.tenant_context"


def _alias_module_names() -> None:
    """Keep both import paths bound to one module object."""

    module = sys.modules[__name__]
    if __name__ == _CANONICAL_MODULE:
        sys.modules[_COMPAT_MODULE] = module
    elif __name__ == _COMPAT_MODULE:
        sys.modules[_CANONICAL_MODULE] = module


_alias_module_names()

# One ContextVar per async context (request, worker task, etc.).
# Default is None; the database event listener fails closed when unset.
_current_tenant_id: ContextVar[Optional[str]] = ContextVar(
    "current_tenant_id",
    default=None,
)


def set_current_tenant(tenant_id: Optional[str]) -> None:
    """Set the tenant ID for the current async context."""

    _current_tenant_id.set(tenant_id)


def get_current_tenant() -> Optional[str]:
    """Get the tenant ID for the current async context."""

    return _current_tenant_id.get()


__all__ = ["get_current_tenant", "set_current_tenant"]
