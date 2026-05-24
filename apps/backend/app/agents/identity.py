"""Agent identity + per-execution identity vocabulary.

Two distinct identity layers — one stable across executions, one
replay-stable per execution:

* `AgentIdentity` — stable. `agent_id` is deployment-pinned (e.g.
  ``"retriever"``, ``"supervisor"``). `runtime_instance_id` is
  derived from the composed runtime's agent set so replays preserve
  the runtime lineage.

* `ExecutionIdentity` — deterministic per `AgentRuntime.execute()` input.
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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.core.deterministic_identity import derive_runtime_id


_AGENT_RUNTIME_NAMESPACE = uuid.UUID(
    "aa6e7001-0001-4001-8001-000000000001"
)
_AGENT_EXECUTION_NAMESPACE = uuid.UUID(
    "aa6e7001-0002-4002-8002-000000000002"
)
_TOOL_INVOCATION_NAMESPACE = uuid.UUID(
    "aa6e7001-0003-4003-8003-000000000003"
)


def derive_agent_runtime_instance_id(
    *,
    agent_ids: Sequence[str],
) -> uuid.UUID:
    """Derive the stable identity of one composed agent runtime."""

    return derive_runtime_id(
        namespace=_AGENT_RUNTIME_NAMESPACE,
        tenant_id=None,
        seed_components=(
            "agent_runtime",
            tuple(sorted(agent_ids)),
        ),
    )


def derive_agent_execution_id(
    *,
    agent_id: str,
    request: Mapping[str, Any],
    tenant_id: str | None,
    correlation_id: uuid.UUID | None,
    parent_execution_id: uuid.UUID | None,
    request_id: str | None,
    metadata: Mapping[str, Any],
) -> uuid.UUID:
    """Derive the replay-stable identity of one agent execution."""

    return derive_runtime_id(
        namespace=_AGENT_EXECUTION_NAMESPACE,
        tenant_id=tenant_id,
        seed_components=(
            "agent_execution",
            agent_id,
            request,
            str(correlation_id) if correlation_id is not None else None,
            (
                str(parent_execution_id)
                if parent_execution_id is not None
                else None
            ),
            request_id,
            metadata,
        ),
    )


def derive_tool_invocation_id(
    *,
    execution_id: uuid.UUID,
    tool_name: str,
    invocation_ordinal: int,
    payload: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> uuid.UUID:
    """Derive the replay-stable identity of one tool invocation."""

    if invocation_ordinal < 1:
        raise ValueError("invocation_ordinal must be >= 1")
    return derive_runtime_id(
        namespace=_TOOL_INVOCATION_NAMESPACE,
        tenant_id=None,
        seed_components=(
            "tool_invocation",
            str(execution_id),
            invocation_ordinal,
            tool_name,
            payload,
            metadata,
        ),
    )


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    """Stable identity of one agent within one runtime instance.

    Attributes:
        agent_id:            Stable, deployment-pinned identifier
                             (e.g. ``"retriever"``). The
                             `AgentRegistry` keys on this.
        runtime_instance_id: UUID of the `AgentRuntime` composition that
                             produced this identity. Replays /
                             supervisor runtimes use this to preserve
                             runtime lineage.
    """

    agent_id: str
    runtime_instance_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ExecutionIdentity:
    """Per-execution identity primitives.

    Derived once per `AgentRuntime.execute()` input. Every value here
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
    "derive_agent_execution_id",
    "derive_agent_runtime_instance_id",
    "derive_tool_invocation_id",
]
