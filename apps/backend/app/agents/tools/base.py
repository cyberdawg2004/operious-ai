"""Tool contract every concrete tool implements.

Tools are pure async callables: ``(request, context) -> result``. They
are NOT responsible for governance, capability checks, constraint
enforcement, or trace recording — the `ToolInvoker` does all of that
around them.

Concrete tools land in future sprints (and in deployment-specific
packages, not in the substrate). Sprint J ships the contract only.

Required class attributes:

* `name`: stable registered identifier.
* `required_capabilities`: frozen set of capability names. The
  invoker rejects calls when the agent's `CapabilitySet` does not
  cover every required name.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from app.agents.context import AgentExecutionContext
from app.agents.results import ToolInvocationRequest, ToolInvocationResult


class BaseTool(ABC):
    """Contract for one tool.

    Subclasses MUST set `name` and `required_capabilities` as class
    attributes (so the registry / invoker can introspect without
    instantiating).
    """

    name: ClassVar[str]
    required_capabilities: ClassVar[frozenset[str]] = frozenset()

    @abstractmethod
    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
    ) -> ToolInvocationResult:
        """Execute the tool. Return a result; raise on failure.

        Errors raised here are caught by the `ToolInvoker` and folded
        into a `failed` invocation envelope.
        """
        raise NotImplementedError


__all__ = ["BaseTool"]
