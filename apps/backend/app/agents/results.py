"""Tool / agent execution result + request value objects.

Three vocabulary types here — the "what crossed the boundary" payloads:

* `ToolInvocationRequest`  — input to one tool call,
* `ToolInvocationResult`   — successful tool output,
* `AgentExecutionResult`   — successful agent execution output.

Failure is represented on the envelope (`error` + status), not by
returning a result variant. This keeps result types narrow and makes
"is_ok branching" the sole control path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ToolInvocationRequest:
    """Input to one tool invocation.

    Attributes:
        tool_name: Stable registered tool identifier.
        payload:   Tool-specific input. Treated opaquely by the
                   substrate; the tool's implementation parses it.
        metadata:  Free-form. The substrate forwards `target_resource`
                   into the governance subject when present.
    """

    tool_name: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolInvocationResult:
    """Successful tool output.

    Attributes:
        output:   Tool-specific structured payload.
        metadata: Free-form. Tools should record any audit-grade
                  context here (model name, latency contributions,
                  upstream IDs).
    """

    output: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentExecutionResult:
    """Successful agent execution output.

    Sprint J ships the contract; concrete agents in future sprints
    populate `output` with whatever shape they produce.
    """

    output: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = [
    "ToolInvocationRequest",
    "ToolInvocationResult",
    "AgentExecutionResult",
]
