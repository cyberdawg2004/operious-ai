"""Agent identity + per-execution identity vocabulary.

Two distinct identity layers — one stable across executions, one
created fresh per execution:

* `AgentIdentity` — stable. `agent_id` is deployment-pinned (e.g.
  ``"retriever"``, ``"supervisor"``). `runtime_instance_id` is created
  once per `AgentRuntime` construction and identifies the
  process-lifetime runtime that produced this execution.

* `ExecutionIdentity` — fresh per `AgentRuntime.execute()` call.
  Carries `execution_id`, `correlation_id` (governance / pipeline
  grouping), `parent_execution_id` (causality chain), and the
  platform-wide `request_id`.

Together these answer the four lineage questions every operational
trace must answer:

1. **Who** ran this? (`agent_id`, `runtime_instance_id`)
2. **Which run** is this? (`execution_id`)
3. **What pipeline** is this part of? (`correlation_id`,
   `request_id`)
4. **What caused** this? (`parent_execution_id`)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    """Stable identity of one agent within one runtime instance.

    Attributes:
        agent_id:            Stable, deployment-pinned identifier
                             (e.g. ``"retriever"``). The
                             `AgentRegistry` keys on this.
        runtime_instance_id: UUID of the `AgentRuntime` that produced
                             this identity. One per runtime
                             construction; replays / supervisor runtimes
                             use this to distinguish process boundaries.
    """

    agent_id: str
    runtime_instance_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ExecutionIdentity:
    """Per-execution identity primitives.

    Created once per `AgentRuntime.execute()` call. Every value here
    is recorded on the `AgentExecutionTrace`; persistence records and
    supervisor queries key on these fields.

    Attributes:
        execution_id:        UUID of THIS execution. The primary key
                             of the execution record.
        correlation_id:      Optional pipeline-level grouping. Threads
                             through governance evaluations as well —
                             see `app.governance.identity.correlation`.
        parent_execution_id: Optional ID of the execution that caused
                             this one. The causality foundation.
                             `parent_chain` on `CausalityMetadata`
                             carries the full ancestor chain when one
                             is known.
        request_id:          Platform-wide request lineage id (sourced
                             from `app.observability.context.get_request_id`
                             when not passed explicitly).
    """

    execution_id: uuid.UUID
    correlation_id: uuid.UUID | None = None
    parent_execution_id: uuid.UUID | None = None
    request_id: str | None = None


__all__ = [
    "AgentIdentity",
    "ExecutionIdentity",
]
