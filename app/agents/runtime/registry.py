"""Agent registry — name-keyed, sorted iteration, composition-time setup.

Same explicit-iteration discipline as `PolicyRegistry` and
`ToolRegistry`: deterministic introspection across processes,
duplicate registration is a configuration error, unknown lookups
raise the typed `AgentNotFoundError` (which `AgentRuntime` catches).
"""

from __future__ import annotations

from typing import Iterator

from app.agents.exceptions import AgentConfigurationError, AgentNotFoundError
from app.agents.runtime.base_agent import BaseAgent


class AgentRegistry:
    """Name → agent lookup."""

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        agent_id = getattr(agent, "agent_id", "")
        if not agent_id:
            raise AgentConfigurationError("agent must have a non-empty agent_id")
        if agent_id in self._agents:
            raise AgentConfigurationError(
                f"agent already registered: {agent_id!r}"
            )
        self._agents[agent_id] = agent

    def get(self, agent_id: str) -> BaseAgent:
        if agent_id not in self._agents:
            raise AgentNotFoundError(f"unknown agent: {agent_id!r}")
        return self._agents[agent_id]

    def has(self, agent_id: str) -> bool:
        return agent_id in self._agents

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._agents.keys()))

    def __iter__(self) -> Iterator[BaseAgent]:
        for agent_id in sorted(self._agents.keys()):
            yield self._agents[agent_id]


__all__ = ["AgentRegistry"]
