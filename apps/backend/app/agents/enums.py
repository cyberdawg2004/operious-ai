"""Agent runtime enum vocabulary.

The single source of truth for typed execution states. Every agent
execution moves through a sequence of these values, recorded as
`StateTransition` entries on the `AgentExecutionTrace`.

The state machine is intentionally small — Sprint J ships a runtime
kernel, not a workflow engine. WAITING and BLOCKED exist so future
agents can model "awaiting tool result" / "awaiting external input"
without forcing the runtime to learn semantics it shouldn't own.

Terminal states (`COMPLETED`, `FAILED`, `CANCELLED`) have no
transitions out — see `state_machine.py` for the transition table.
"""

from __future__ import annotations

from enum import StrEnum


class ExecutionState(StrEnum):
    """Typed agent execution state.

    NOT a boolean. NOT a free-form string. Every transition is
    validated by `state_machine.assert_transition()`; every transition
    is recorded on the trace.
    """

    CREATED = "created"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CapabilityScope(StrEnum):
    """Coarse-grained scope an agent capability operates within.

    Capabilities are strings (`"retrieval.read"`, `"tool.search"`);
    the scope discriminates the *kind* of operation. Tool-level access
    checks combine `(capability_name, scope)` to decide whether an
    action is permitted.

    `INVOKE` covers tool calls; `ESCALATE` is reserved for capabilities
    that can hand off to a supervisor runtime (Sprint K+).
    """

    READ = "read"
    WRITE = "write"
    INVOKE = "invoke"
    ESCALATE = "escalate"


class ToolInvocationStatus(StrEnum):
    """Outcome status emitted by the tool invoker.

    `denied` is distinct from `failed`: denied means governance or a
    constraint blocked the call before the tool ran; failed means the
    tool itself raised. Supervisor runtimes care about the
    distinction.
    """

    OK = "ok"
    FAILED = "failed"
    DENIED = "denied"


__all__ = [
    "ExecutionState",
    "CapabilityScope",
    "ToolInvocationStatus",
]
