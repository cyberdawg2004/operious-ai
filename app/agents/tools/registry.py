"""Tool registry — name-keyed, sorted iteration, composition-time setup.

Mirrors the discipline of `PolicyRegistry` and `AgentRegistry`:

* registered at composition time (DI),
* duplicate registration is a configuration error,
* iteration is explicitly sorted by name (deterministic introspection),
* unknown lookups raise `ToolNotFoundError` (caught by the invoker).
"""

from __future__ import annotations

from typing import Iterator

from app.agents.exceptions import ToolConfigurationError, ToolNotFoundError
from app.agents.tools.base import BaseTool


class ToolRegistry:
    """Name → tool lookup."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if not getattr(tool, "name", ""):
            raise ToolConfigurationError("tool must have a non-empty name")
        if tool.name in self._tools:
            raise ToolConfigurationError(
                f"tool already registered: {tool.name!r}"
            )
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise ToolNotFoundError(f"unknown tool: {name!r}")
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools.keys()))

    def __iter__(self) -> Iterator[BaseTool]:
        for name in sorted(self._tools.keys()):
            yield self._tools[name]


__all__ = ["ToolRegistry"]
