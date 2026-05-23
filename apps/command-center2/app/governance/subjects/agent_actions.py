"""Agent-action governance subject — future-proofing for Sprint J / L.

This subject is **stubbed in place** for the agent runtime that lands
in a later sprint. No builtin policy operates on it yet; no factory
constructs it from operational types. The contract exists so that
when the agent runtime ships, governance integration is a pure
addition — no substrate changes needed.

Design rationale: governance subjects are part of the substrate
vocabulary, not part of the agent runtime. The vocabulary must be
stable before the runtime that depends on it is built — otherwise the
agent runtime's first wiring would force a substrate-level migration.

Fields are designed to support:

* per-agent capability gating (`agent_id`, `capability`),
* per-tool action gating (`tool_name`, `target_resource`),
* execution-scope semantics (`execution_scope`, e.g.
  "tenant:acme/workflow:onboarding"),
* supervisor-runtime introspection (`supervisor_context`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.governance.subjects.base import BaseGovernanceSubject, SubjectKind


@dataclass(frozen=True, slots=True)
class AgentActionGovernanceSubject(BaseGovernanceSubject):
    """Governance subject for an agent attempting a runtime action.

    Attributes:
        agent_id:           Stable agent identifier (Sprint J vocabulary).
        capability:         Capability the agent is invoking (e.g.
                            "retrieval.read", "tool.call", "memory.write").
        tool_name:          Concrete tool the action targets, if any.
        target_resource:    What the action operates on (stable
                            colon-delimited identifier).
        execution_scope:    Scope the action runs within (workflow,
                            tenant, request). Free-form structured
                            string; supervisor runtimes parse it.
        supervisor_context: Structured metadata the supervisor runtime
                            uses to correlate the action against
                            higher-level operational plans.
        request_id:         Platform-wide request lineage id.
        tenant_id:          Tenant scope.
        metadata:           Free-form structured payload.
    """

    agent_id: str = ""
    capability: str = ""
    tool_name: str | None = None
    target_resource: str = ""
    execution_scope: str = ""
    supervisor_context: Mapping[str, Any] = field(default_factory=dict)
    request_id: str | None = None
    tenant_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    kind: SubjectKind = SubjectKind.AGENT_ACTION

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "agent_id": self.agent_id,
            "capability": self.capability,
            "tool_name": self.tool_name,
            "target_resource": self.target_resource,
            "execution_scope": self.execution_scope,
            "supervisor_context": dict(self.supervisor_context),
            "request_id": self.request_id,
            "tenant_id": self.tenant_id,
            "metadata": dict(self.metadata),
        }


__all__ = ["AgentActionGovernanceSubject"]
