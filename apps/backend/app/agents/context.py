"""Per-execution agent context.

`AgentExecutionContext` is the single value object handed to:

* every `BaseAgent.run(request, context, session)` call,
* every tool's `BaseTool.invoke(request, context)` call,
* every `ToolInvoker.invoke(request, context)` call.

It is the **read-only snapshot** of who-am-I / what-am-I-allowed /
under-what-pipeline data the runtime computed at execution start.
Frozen, slot-based, replay-safe.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agents.capabilities import CapabilitySet, ExecutionConstraints
from app.agents.identity import AgentIdentity, ExecutionIdentity
from app.agents.value_objects import CausalityMetadata
from app.identity import AuthorityContext
from app.types.json import JsonObject, MetadataMap


def _empty_json_object() -> JsonObject:
    return {}


@dataclass(frozen=True, slots=True)
class AgentExecutionContext:
    """Read-only execution context handed to agents and tools.

    Attributes:
        identity:     Stable identity (`agent_id`, `runtime_instance_id`).
        execution:    Per-execution identity (`execution_id`,
                      `correlation_id`, `parent_execution_id`,
                      `request_id`).
        capabilities: Capability set in effect for THIS execution.
                      Defaults to the agent's declared set; callers
                      MAY narrow it per execution.
        constraints:  Operational constraints for THIS execution.
        causality:    Lineage payload (initiator / cause /
                      parent_chain).
        tenant_id:    Optional tenant scope. Forwarded into
                      governance subjects when set.
        authority:    Optional reference to the typed authority
                      tuple (Wedge B2). When present, every axis
                      (principal / organization / environment) is
                      projected onto the governance context for
                      tool-invocation legality so policies and the
                      resulting :class:`GovernanceTrace` carry the
                      full attribution chain (Wedge 2.75-γ).
        metadata:     Free-form structured execution metadata.
    """

    identity: AgentIdentity
    execution: ExecutionIdentity
    capabilities: CapabilitySet
    constraints: ExecutionConstraints
    causality: CausalityMetadata
    tenant_id: str | None = None
    authority: AuthorityContext | None = None
    metadata: MetadataMap = field(default_factory=_empty_json_object)


__all__ = ["AgentExecutionContext"]
