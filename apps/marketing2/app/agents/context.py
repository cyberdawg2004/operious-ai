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
from typing import Any, Mapping

from app.agents.capabilities import CapabilitySet, ExecutionConstraints
from app.agents.identity import AgentIdentity, ExecutionIdentity
from app.agents.value_objects import CausalityMetadata


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
        metadata:     Free-form structured execution metadata.
    """

    identity: AgentIdentity
    execution: ExecutionIdentity
    capabilities: CapabilitySet
    constraints: ExecutionConstraints
    causality: CausalityMetadata
    tenant_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["AgentExecutionContext"]
