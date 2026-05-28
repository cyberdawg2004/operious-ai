"""Tool runtime — explicit, typed, traceable, governed.

Three runtime pieces:

* `BaseTool`         — the contract every tool implements.
* `ToolCapability`  — side-effect tier (READ_ONLY vs ACTION).
* `ToolRegistry`     — name → tool lookup; sorted iteration.
* `ToolInvoker`      — single bridge that wraps governance + capability
                       + constraint checks around a tool call.
* `AgentToolSession` — per-execution wrapper handed to agents that
                       captures every invocation envelope.

The integration with governance lives in `ToolInvoker`. Agents see
only `AgentToolSession`. This keeps governance internals out of the
agent layer entirely.
"""

from app.agents.tools.base import BaseTool
from app.agents.tools.capability import ToolCapability
from app.agents.tools.invoker import ToolInvoker
from app.agents.tools.registry import ToolRegistry
from app.agents.tools.session import AgentToolSession

__all__ = [
    "BaseTool",
    "ToolCapability",
    "ToolRegistry",
    "ToolInvoker",
    "AgentToolSession",
]
