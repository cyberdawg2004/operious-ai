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
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from app.governance.enums import EnforcementStage
from app.governance.subjects.base import (
    BaseGovernanceSubject,
    GenericGovernanceSubject,
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
                         traces and restrictions.
        request_id:      Platform-wide request id; sourced from
                         `app.observability.context.get_request_id()`
                         at call sites that build the context.
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
    tenant_id: str | None = None
    request_id: str | None = None
    subject: BaseGovernanceSubject = field(default_factory=GenericGovernanceSubject)
    correlation_id: uuid.UUID | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["GovernanceContext"]
