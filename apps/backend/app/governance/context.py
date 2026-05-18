"""Governance request-scoped context.

Sprint I Hardening: `subject` is now a **typed
`BaseGovernanceSubject`** (replacing the loose `Mapping[str, Any]`
of Sprint I). The default factory is `GenericGovernanceSubject` for
migration compatibility — new code uses one of the typed subjects
under `app/governance/subjects/`.

A `correlation_id` field links multiple governance evaluations
performed under one logical operational pipeline (e.g. PRE_RETRIEVAL
+ PRE_EXECUTION under one `GovernedAssemblyRuntime.assemble()` call).
The composition layer sets it; persistence queries use it.

Architectural note: `subject` is a typed value object, NOT a
reference to live mutable state. Treat the context as a snapshot —
the policy chain is free to be invoked multiple times against the
same context.

2.5-F: ``GovernanceContext`` now carries the typed identity axes —
``principal_id``, ``organization_id``, ``environment_id`` — and a
reference to the singular ``AuthorityContext`` aggregate produced at
HTTP ingress. ``tenant_id`` is retained as the primary tenant axis
for backward compatibility but is now typed as ``TenantId | None``;
when both ``tenant_id`` and ``authority`` are populated, a
``__post_init__`` invariant rejects mismatched values so the
governance substrate cannot drift away from the singular authority
resolution.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from app.governance.enums import EnforcementStage
from app.governance.exceptions import GovernanceConfigurationError
from app.governance.subjects.base import (
    BaseGovernanceSubject,
    GenericGovernanceSubject,
)
from app.identity import (
    AuthorityContext,
    EnvironmentId,
    OrganizationId,
    PrincipalId,
    TenantId,
)


@dataclass(frozen=True, slots=True)
class GovernanceContext:
    """Request-scoped, immutable evaluation input.

    Attributes:
        stage:           Which enforcement stage this evaluation
                         pertains to.
        action:          Stable, namespaced action string the system
                         is considering (e.g. "rag.assemble_context",
                         "ai.completion"). Mirrors the audit-event
                         action vocabulary.
        resource:        Stable identifier of what is being acted on
                         (e.g. "tenant:acme/index:default").
        actor:           Who/what initiated the action.
        tenant_id:       Optional tenant scope; propagated into
                         traces and restrictions. Typed
                         ``TenantId | None`` (2.5-F).
        request_id:      Platform-wide request id; sourced from
                         `app.observability.context.get_request_id()`
                         at call sites that build the context.
        principal_id:    Optional typed principal axis (2.5-F).
        organization_id: Optional typed organization axis (2.5-F).
        environment_id:  Optional typed environment axis (2.5-F).
        authority:       Optional reference to the singular
                         ``AuthorityContext`` aggregate produced at
                         HTTP ingress. When set, its tenant axis MUST
                         match ``tenant_id`` (or ``tenant_id`` is
                         ``None``); enforced by ``__post_init__``.
        subject:         **Typed governance subject** the policies
                         evaluate against. Discriminated by
                         `subject.kind`; the engine routes policies
                         based on their `applicable_subject_kinds`.
        correlation_id:  Optional higher-level grouping for multi-stage
                         governance pipelines. See
                         `app.governance.identity.correlation`.
        metadata:        Opaque; propagated into the trace.
    """

    stage: EnforcementStage
    action: str
    resource: str
    actor: str = "system"
    tenant_id: TenantId | None = None
    request_id: str | None = None
    principal_id: PrincipalId | None = None
    organization_id: OrganizationId | None = None
    environment_id: EnvironmentId | None = None
    authority: AuthorityContext | None = None
    subject: BaseGovernanceSubject = field(default_factory=GenericGovernanceSubject)
    correlation_id: uuid.UUID | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 2.5-F invariant: when both ``tenant_id`` and ``authority``
        # are set, they MUST agree on the tenant axis. Without this
        # invariant the two fields silently drift in production
        # (multi-tenant audit decisions against the wrong tenant).
        if self.authority is not None and self.tenant_id is not None:
            if self.authority.tenant_id != self.tenant_id:
                raise GovernanceConfigurationError(
                    "GovernanceContext.tenant_id and "
                    "GovernanceContext.authority.tenant_id disagree: "
                    f"{self.tenant_id!r} vs "
                    f"{self.authority.tenant_id!r}"
                )


__all__ = ["GovernanceContext"]
