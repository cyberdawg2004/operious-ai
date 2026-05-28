"""Capability governance subject — RBAC evaluation input (Branch B).

Constitutional positioning
──────────────────────────
Authority verification (Branch C) answers "who is this caller?".
Capability evaluation (Branch B) answers "is this caller
authorized for THIS operation?". The two are constitutionally
distinct:

* :class:`app.identity.AuthorityContext` carries an opaque
  ``capabilities: frozenset[str]`` granted by the upstream auth
  provider (claims-derived). The substrate does not interpret
  capability names.
* :class:`CapabilityGovernanceSubject` names the SINGLE
  capability the current operation requires and carries the
  HELD set the caller offered. A single :class:`RBACPolicy`
  evaluates the predicate ``required in held`` and produces a
  ``Decision.DENY`` (fail-closed, AUTHORITY-class) or
  ``Decision.ALLOW``.

Capability legality is checked PER OPERATION, not per request.
The call site that builds the :class:`GovernanceContext`
synthesises the subject from
``request.state.authority.capabilities`` (held) plus the
operation's declared requirement (required).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.governance.subjects.base import (
    BaseGovernanceSubject,
    SubjectKind,
)
from app.types.json import JsonObject


def _empty_json_object() -> JsonObject:
    return {}


@dataclass(frozen=True, slots=True)
class CapabilityGovernanceSubject(BaseGovernanceSubject):
    """Canonical capability-evaluation subject.

    Attributes:
        required_capability: The capability the operation needs.
                             Empty string is rejected by
                             :class:`RBACPolicy` as
                             ``capability_unspecified`` (DENY).
        held_capabilities:   The capabilities the caller offered
                             (typically copied from
                             ``AuthorityContext.capabilities`` at
                             the call site that built the context).
        tenant_id:           Tenant scope at the time of evaluation.
        actor:               Free-form attribution of the caller
                             (mirrors ``GovernanceContext.actor``).
        metadata:            Opaque; propagated onto the trace.
    """

    required_capability: str = ""
    held_capabilities: frozenset[str] = frozenset()
    tenant_id: str | None = None
    actor: str = "system"
    metadata: Mapping[str, Any] = field(default_factory=_empty_json_object)
    kind: SubjectKind = SubjectKind.CAPABILITY

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "required_capability": self.required_capability,
            "held_capabilities": sorted(self.held_capabilities),
            "tenant_id": self.tenant_id,
            "actor": self.actor,
            "metadata": dict(self.metadata),
        }


__all__ = ["CapabilityGovernanceSubject"]
