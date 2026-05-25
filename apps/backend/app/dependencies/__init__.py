"""Constitutional FastAPI dependency providers.

Two small modules, each owning one wiring concern:

* `database` — async session + session factory.
* `services` — services composed from repositories and primitives.

Routers depend on `services` (and occasionally on a repository
directly for read-only auxiliary endpoints). Services and
repositories never import from this package — providers depend on
them, not the other way around.

Phase 2.1 quarantine note:

* `dependencies.orchestration`, `dependencies.governance` (legacy
  document/chunk-centric DI, NOT the constitutional governance
  substrate), `dependencies.memory`, `dependencies.rag`,
  `dependencies.providers`, and `dependencies.repositories` were
  quarantined under `app._deprecated.dependencies.*`. Constitutional
  substrate DI providers (session, governance, coordination,
  arbitration, boundary, organizational_intelligence) will land in
  Phase 2.4 and Phase 2.5, sourced from the request authority
  envelope.

Tenant scope (Wedge 2.75-ε composition root)
────────────────────────────────────────────
`dependencies.authority` exposes the canonical
:func:`~app.dependencies.authority.require_tenant_scope` and
:func:`~app.dependencies.authority.request_tenant_scope_opt`
helpers. Every public read handler that returns tenant-scoped
resources MUST source its persistence ``expected_tenant_id``
argument through one of these dependencies. This is the
composition-root wedge that enforces row-level tenant isolation
at the HTTP boundary.
"""

from app.dependencies.authority import (
    ERROR_CODE_AUTHORITY_REQUIRED,
    ERROR_CODE_OPERATOR_AUTHORITY_REQUIRED,
    ERROR_CODE_TENANT_AXIS_MISSING,
    OPERATOR_CAPABILITY,
    request_authority_opt,
    request_tenant_scope_opt,
    require_authority,
    require_operator_authority,
    require_tenant_scope,
)

__all__ = [
    "ERROR_CODE_AUTHORITY_REQUIRED",
    "ERROR_CODE_OPERATOR_AUTHORITY_REQUIRED",
    "ERROR_CODE_TENANT_AXIS_MISSING",
    "OPERATOR_CAPABILITY",
    "request_authority_opt",
    "request_tenant_scope_opt",
    "require_authority",
    "require_operator_authority",
    "require_tenant_scope",
]
