"""Agent contract every concrete agent implements.

Three responsibilities of a concrete agent:

* declare its `agent_id` (stable),
* declare its `declared_capabilities` (the substrate uses these to
  build the default `CapabilitySet` per execution),
* implement `run()` — the agent's actual logic, called by
  `AgentRuntime`.

Sprint J ships the contract only. Subclasses live in future sprints
or in deployment-specific packages — never in the substrate.

`run()` receives:

* `request`: opaque structured input (whatever the caller passed to
  `AgentRuntime.execute()`),
* `context`: read-only `AgentExecutionContext` snapshot,
* `session`: per-execution `AgentToolSession` for tool calls.

`run()` returns an `AgentExecutionResult`. Errors raised inside
`run()` are caught by the runtime and folded into a failed envelope
— concrete agents may raise freely; the runtime classifies and
records.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Mapping

from app.agents.capabilities import AgentCapability
from app.agents.context import AgentExecutionContext
from app.agents.results import AgentExecutionResult
from app.agents.tools.session import AgentToolSession


class BaseAgent(ABC):
    """Abstract base for every concrete agent.

    Subclasses MUST set:

    * `agent_id`              — stable registered identifier,
    * `declared_capabilities` — tuple of `AgentCapability` the agent
                                  needs to operate. Used as the
                                  default capability set per execution
                                  unless the caller overrides.
    """

    agent_id: ClassVar[str]
    declared_capabilities: ClassVar[tuple[AgentCapability, ...]] = ()

    @abstractmethod
    async def run(
        self,
        request: Mapping[str, Any],
        context: AgentExecutionContext,
        session: AgentToolSession,
    ) -> AgentExecutionResult:
        """Execute the agent's logic. Return a result; raise on
        unrecoverable failure (the runtime folds the raise into a
        failed envelope).
        """
        raise NotImplementedError


__all__ = ["BaseAgent"]
