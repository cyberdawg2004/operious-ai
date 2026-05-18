"""Identity substrate.

Owns the typed identity primitives that anchor authority across
Operious AI: ``TenantId``, ``PrincipalId``, ``OrganizationId``,
``EnvironmentId``, their ``coerce_*`` helpers, and ``IdentityError``.

This substrate is a LEAF — it must not import from any sibling
substrate (governance, session, hardening, arbitration, boundary,
coordination, agents, supervisor, organizational_intelligence, api,
services, repositories, db, middleware, observability, dependencies).
Sibling substrates may freely import from ``app.identity``.

See ``app.identity.primitives`` for the full doctrine, and
``tests/test_identity_primitives.py`` for the leaf-invariant guard.
"""

from app.identity.authority import (
    AuthorityContext,
    AuthorityResolution,
    AuthoritySource,
    resolve_authority,
)
from app.identity.primitives import (
    EnvironmentId,
    IdentityError,
    OrganizationId,
    PrincipalId,
    TenantId,
    coerce_environment_id,
    coerce_organization_id,
    coerce_principal_id,
    coerce_tenant_id,
)
from app.identity.projection import project_optional_str

__all__ = [
    "AuthorityContext",
    "AuthorityResolution",
    "AuthoritySource",
    "EnvironmentId",
    "IdentityError",
    "OrganizationId",
    "PrincipalId",
    "TenantId",
    "coerce_environment_id",
    "coerce_organization_id",
    "coerce_principal_id",
    "coerce_tenant_id",
    "project_optional_str",
    "resolve_authority",
]
