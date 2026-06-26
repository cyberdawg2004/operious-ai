"""Constitutional FastAPI dependency providers.

Two small modules, each owning one wiring concern:

* `database` — async session + session factory.
* `services` — services composed from repositories and primitives.

Routers depend on `services` (and occasionally on a repository
directly for read-only auxiliary endpoints). Services and
repositories never import from this package — providers depend on
them, not the other way around.

Phase 2.1 cleanup note:

* `dependencies.orchestration`, `dependencies.governance` (legacy
  document/chunk-centric DI, NOT the constitutional governance
  substrate), `dependencies.memory`, `dependencies.rag`,
  `dependencies.providers`, and `dependencies.repositories` were
  removed with the legacy quarantine. Constitutional substrate DI
  providers (session, governance, coordination, arbitration, boundary,
  organizational_intelligence) will land in Phase 2.4 and Phase 2.5,
  sourced from the request authority envelope.

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
    ERROR_CODE_AUTHORIZED_SCOPE_REQUIRED,
    ERROR_CODE_CAPABILITY_REQUIRED,
    ERROR_CODE_INDEPENDENT_APPROVAL_REQUIRED,
    ERROR_CODE_OPERATOR_AUTHORITY_REQUIRED,
    ERROR_CODE_TENANT_AXIS_MISSING,
    OPERATOR_CAPABILITY,
    PLATFORM_TENANT_ADMIN_CAPABILITY,
    TENANT_ACTIONS_APPROVE_CAPABILITY,
    TENANT_ADMIN_CAPABILITY,
    TENANT_APPROVALS_READ_CAPABILITY,
    TENANT_AUDIT_EXPORT_CAPABILITY,
    TENANT_CHANNEL_ADMIN_CAPABILITY,
    TENANT_COGNITION_READ_CAPABILITY,
    TENANT_CONNECTOR_APPROVE_CAPABILITY,
    TENANT_CONNECTOR_READ_CAPABILITY,
    TENANT_CONNECTOR_WRITE_CAPABILITY,
    TENANT_CONFIG_APPROVE_CAPABILITY,
    TENANT_CONFIG_DOMAIN_WRITE_CAPABILITIES,
    TENANT_CONFIG_READ_CAPABILITY,
    TENANT_CONFIG_WRITE_CAPABILITY,
    TENANT_EXECUTION_GOVERNANCE_WRITE_CAPABILITY,
    TENANT_GOVERNANCE_READ_CAPABILITY,
    TENANT_KNOWLEDGE_WRITE_CAPABILITY,
    TENANT_OBSERVABILITY_READ_CAPABILITY,
    TENANT_OPERATIONS_READ_CAPABILITY,
    TENANT_POLICY_WRITE_CAPABILITY,
    TENANT_PRIVACY_ADMIN_CAPABILITY,
    TENANT_PRIVACY_APPROVE_CAPABILITY,
    TENANT_RESOLUTION_GUIDE_CAPABILITY,
    TENANT_SUPERVISOR_READ_CAPABILITY,
    TENANT_TRAINING_WRITE_CAPABILITY,
    TENANT_TOPOLOGY_WRITE_CAPABILITY,
    request_authority_opt,
    request_tenant_scope_opt,
    require_authority,
    require_capability,
    require_config_apply_authorization,
    require_config_apply_authorization_for,
    require_operator_authority,
    require_platform_tenant_admin,
    require_tenant_actions_approve,
    require_tenant_admin,
    require_tenant_approvals_read,
    require_tenant_audit_export,
    require_tenant_cognition_read,
    require_tenant_connector_approve,
    require_tenant_connector_read,
    require_tenant_governance_read,
    require_tenant_knowledge_write,
    require_tenant_observability_read,
    require_tenant_operations_read,
    require_tenant_privacy_admin,
    require_tenant_privacy_approve,
    require_tenant_resolution_guide,
    require_tenant_scope,
    require_tenant_supervisor_read,
    require_tenant_training_write,
)

__all__ = [
    "ERROR_CODE_AUTHORITY_REQUIRED",
    "ERROR_CODE_AUTHORIZED_SCOPE_REQUIRED",
    "ERROR_CODE_CAPABILITY_REQUIRED",
    "ERROR_CODE_INDEPENDENT_APPROVAL_REQUIRED",
    "ERROR_CODE_OPERATOR_AUTHORITY_REQUIRED",
    "ERROR_CODE_TENANT_AXIS_MISSING",
    "OPERATOR_CAPABILITY",
    "PLATFORM_TENANT_ADMIN_CAPABILITY",
    "TENANT_ACTIONS_APPROVE_CAPABILITY",
    "TENANT_ADMIN_CAPABILITY",
    "TENANT_APPROVALS_READ_CAPABILITY",
    "TENANT_AUDIT_EXPORT_CAPABILITY",
    "TENANT_CHANNEL_ADMIN_CAPABILITY",
    "TENANT_COGNITION_READ_CAPABILITY",
    "TENANT_CONNECTOR_APPROVE_CAPABILITY",
    "TENANT_CONNECTOR_READ_CAPABILITY",
    "TENANT_CONNECTOR_WRITE_CAPABILITY",
    "TENANT_CONFIG_APPROVE_CAPABILITY",
    "TENANT_CONFIG_DOMAIN_WRITE_CAPABILITIES",
    "TENANT_CONFIG_READ_CAPABILITY",
    "TENANT_CONFIG_WRITE_CAPABILITY",
    "TENANT_EXECUTION_GOVERNANCE_WRITE_CAPABILITY",
    "TENANT_GOVERNANCE_READ_CAPABILITY",
    "TENANT_KNOWLEDGE_WRITE_CAPABILITY",
    "TENANT_OBSERVABILITY_READ_CAPABILITY",
    "TENANT_OPERATIONS_READ_CAPABILITY",
    "TENANT_POLICY_WRITE_CAPABILITY",
    "TENANT_PRIVACY_ADMIN_CAPABILITY",
    "TENANT_PRIVACY_APPROVE_CAPABILITY",
    "TENANT_RESOLUTION_GUIDE_CAPABILITY",
    "TENANT_SUPERVISOR_READ_CAPABILITY",
    "TENANT_TRAINING_WRITE_CAPABILITY",
    "TENANT_TOPOLOGY_WRITE_CAPABILITY",
    "request_authority_opt",
    "request_tenant_scope_opt",
    "require_authority",
    "require_capability",
    "require_config_apply_authorization",
    "require_config_apply_authorization_for",
    "require_operator_authority",
    "require_platform_tenant_admin",
    "require_tenant_actions_approve",
    "require_tenant_admin",
    "require_tenant_approvals_read",
    "require_tenant_audit_export",
    "require_tenant_cognition_read",
    "require_tenant_connector_approve",
    "require_tenant_connector_read",
    "require_tenant_governance_read",
    "require_tenant_knowledge_write",
    "require_tenant_observability_read",
    "require_tenant_operations_read",
    "require_tenant_privacy_admin",
    "require_tenant_privacy_approve",
    "require_tenant_resolution_guide",
    "require_tenant_scope",
    "require_tenant_supervisor_read",
    "require_tenant_training_write",
]
