"""Fail-closed action tool — governed error when no real connector is configured.

In production an action whose tenant has no configured connector MUST NOT return
a fake ``success`` envelope (the old stub behaviour). Instead it returns a
governed ``error`` so the agent escalates to a human rather than telling a
customer an action happened when it did not.
"""

from __future__ import annotations

from app.agents.context import AgentExecutionContext
from app.agents.results import ToolInvocationRequest, ToolInvocationResult
from app.agents.tools.base import BaseTool
from app.agents.tools.capability import ToolCapability

_ERROR_CODE = "action_connector_not_configured"


class FailClosedActionTool(BaseTool):
    """A tool that always fails closed with a governed error.

    Carries the same ``name`` / ``capability`` / ``required_capabilities`` as the
    real action it stands in for, so governance, grants, and capability checks
    behave identically — only the outcome is a deterministic, audited failure
    instead of a fake success.
    """

    def __init__(
        self,
        *,
        name: str,
        capability: ToolCapability,
        required_capabilities: frozenset[str],
        reason: str,
    ) -> None:
        if not name:
            raise ValueError("FailClosedActionTool requires a non-empty name")
        self._name = name
        self._capability = capability
        self._required_capabilities = required_capabilities
        self._reason = reason

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    @property
    def capability(self) -> ToolCapability:  # type: ignore[override]
        return self._capability

    @property
    def required_capabilities(self) -> frozenset[str]:  # type: ignore[override]
        return self._required_capabilities

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
    ) -> ToolInvocationResult:
        del request, context  # outcome does not depend on input — always fail closed.
        return ToolInvocationResult(
            output={"status": "error"},
            metadata={"tool": self._name, "fail_closed": True},
            status="error",
            error_code=_ERROR_CODE,
            error_message=self._reason,
        )


__all__ = ["FailClosedActionTool"]
