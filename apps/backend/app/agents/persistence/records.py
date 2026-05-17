"""Persistable agent runtime record shapes.

Frozen, JSON-serializable, storage-agnostic. Every record:

* is `@dataclass(frozen=True, slots=True)`,
* has `to_dict()` / `from_dict()` for stable JSON serialization,
* uses string identifiers (UUIDs are stringified at the boundary;
  timestamps are ISO-8601 strings) for cross-system portability,
* carries the audit-grade fields supervisor runtimes will query
  against (execution_id, correlation_id, parent_execution_id,
  governance_decision_ids, etc.).

These records are the persistence contract — the shape that queryable
agent execution history takes. A future Postgres / Elasticsearch / S3
backend serialises into / out of these records; the runtime substrate
doesn't change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class StateTransitionRecord:
    """Persistable shape of one state transition.

    Embedded in `AgentExecutionRecord.state_transitions` — not stored
    standalone.
    """

    from_state: str
    to_state: str
    transitioned_at: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_state": self.from_state,
            "to_state": self.to_state,
            "transitioned_at": self.transitioned_at,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StateTransitionRecord":
        return cls(
            from_state=str(data["from_state"]),
            to_state=str(data["to_state"]),
            transitioned_at=str(data["transitioned_at"]),
            reason=str(data.get("reason", "")),
        )


@dataclass(frozen=True, slots=True)
class ToolInvocationRecord:
    """Persistable shape of one tool invocation."""

    invocation_id: str
    execution_id: str
    tool_name: str
    status: str
    started_at: str
    ended_at: str
    latency_ms: float
    governance_decision_id: str | None = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "invocation_id": self.invocation_id,
            "execution_id": self.execution_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "latency_ms": self.latency_ms,
            "governance_decision_id": self.governance_decision_id,
            "error": self.error,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ToolInvocationRecord":
        return cls(
            invocation_id=str(data["invocation_id"]),
            execution_id=str(data["execution_id"]),
            tool_name=str(data["tool_name"]),
            status=str(data["status"]),
            started_at=str(data["started_at"]),
            ended_at=str(data["ended_at"]),
            latency_ms=float(data["latency_ms"]),
            governance_decision_id=(
                str(data["governance_decision_id"])
                if data.get("governance_decision_id") is not None
                else None
            ),
            error=(
                str(data["error"]) if data.get("error") is not None else None
            ),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class AgentExecutionRecord:
    """Persistable shape of one agent execution.

    Carries the full execution lineage: identity, causality (parent
    chain), state transitions, tool invocation lineage, governance
    decision lineage. Sufficient on its own (plus the per-invocation
    `ToolInvocationRecord`s) to reconstruct the execution for replay
    or supervisor inspection.
    """

    execution_id: str
    runtime_instance_id: str
    agent_id: str
    correlation_id: str | None
    parent_execution_id: str | None
    parent_chain: tuple[str, ...]
    request_id: str | None
    tenant_id: str | None
    final_state: str
    started_at: str
    ended_at: str
    latency_ms: float
    state_transitions: tuple[StateTransitionRecord, ...]
    tool_invocation_count: int
    tool_invocation_ids: tuple[str, ...] = ()
    governance_decision_ids: tuple[str, ...] = ()
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "runtime_instance_id": self.runtime_instance_id,
            "agent_id": self.agent_id,
            "correlation_id": self.correlation_id,
            "parent_execution_id": self.parent_execution_id,
            "parent_chain": list(self.parent_chain),
            "request_id": self.request_id,
            "tenant_id": self.tenant_id,
            "final_state": self.final_state,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "latency_ms": self.latency_ms,
            "state_transitions": [t.to_dict() for t in self.state_transitions],
            "tool_invocation_count": self.tool_invocation_count,
            "tool_invocation_ids": list(self.tool_invocation_ids),
            "governance_decision_ids": list(self.governance_decision_ids),
            "error": self.error,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AgentExecutionRecord":
        return cls(
            execution_id=str(data["execution_id"]),
            runtime_instance_id=str(data["runtime_instance_id"]),
            agent_id=str(data["agent_id"]),
            correlation_id=(
                str(data["correlation_id"])
                if data.get("correlation_id") is not None
                else None
            ),
            parent_execution_id=(
                str(data["parent_execution_id"])
                if data.get("parent_execution_id") is not None
                else None
            ),
            parent_chain=tuple(str(x) for x in data.get("parent_chain") or ()),
            request_id=(
                str(data["request_id"])
                if data.get("request_id") is not None
                else None
            ),
            tenant_id=(
                str(data["tenant_id"])
                if data.get("tenant_id") is not None
                else None
            ),
            final_state=str(data["final_state"]),
            started_at=str(data["started_at"]),
            ended_at=str(data["ended_at"]),
            latency_ms=float(data["latency_ms"]),
            state_transitions=tuple(
                StateTransitionRecord.from_dict(t)
                for t in data.get("state_transitions") or ()
            ),
            tool_invocation_count=int(data.get("tool_invocation_count", 0)),
            tool_invocation_ids=tuple(
                str(x) for x in data.get("tool_invocation_ids") or ()
            ),
            governance_decision_ids=tuple(
                str(x) for x in data.get("governance_decision_ids") or ()
            ),
            error=(
                str(data["error"]) if data.get("error") is not None else None
            ),
            metadata=dict(data.get("metadata") or {}),
        )


__all__ = [
    "StateTransitionRecord",
    "ToolInvocationRecord",
    "AgentExecutionRecord",
]
