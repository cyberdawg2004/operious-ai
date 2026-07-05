"""Tool registry — name-keyed, sorted iteration, composition-time setup.

Mirrors the discipline of `PolicyRegistry` and `AgentRegistry`:

* registered at composition time (DI),
* duplicate registration is a configuration error,
* iteration is explicitly sorted by name (deterministic introspection),
* unknown lookups raise `ToolNotFoundError` (caught by the invoker).

Also provides `TenantConnectorRegistry` — an async resolver that returns
the set of active connector tool_names for a given tenant from persistence.
This is the runtime component of MVP-2: non-commerce tenants register their
own action tool names via connector config; this class makes those names
available to validation and governance paths without hardcoding them.
"""

from __future__ import annotations

from typing import Iterator, Protocol

from app.agents.exceptions import ToolConfigurationError, ToolNotFoundError
from app.agents.tools.base import BaseTool


class TenantConnectorRegistryProtocol(Protocol):
    """Protocol for resolving tenant-registered connector tool names."""

    async def resolve(self, *, tenant_id: str) -> frozenset[str]: ...


class TenantConnectorRegistry:
    """Resolve the set of active connector tool_names for a given tenant.

    Queries the tenant's connector configuration records via the
    TenantConfigurationRepository and returns every tool_name whose
    status is 'active'.  Commerce tenants will have the four built-in
    e-commerce connectors; non-commerce tenants will have their own
    registered tool names (e.g. "account.credit", "service.ticket").

    Tenant-isolation: every lookup is scoped to `tenant_id` via
    `expected_tenant_id` enforcement in the repository.
    """

    def __init__(
        self,
        *,
        repository: "TenantConnectorRepositoryProtocol",
    ) -> None:
        self._repository = repository

    async def resolve(self, *, tenant_id: str) -> frozenset[str]:
        """Return frozenset of active connector tool_names for the tenant."""
        from app.tenant.persistence.models import TenantConnectorConfigurationQuery

        page = await self._repository.list_connector_configurations(
            TenantConnectorConfigurationQuery(status="active"),
            expected_tenant_id=tenant_id,
        )
        return frozenset(record.tool_name for record in page.items)


class TenantConnectorRepositoryProtocol(Protocol):
    """Protocol interface for listing connector configurations."""

    async def list_connector_configurations(
        self,
        query: object,
        *,
        expected_tenant_id: str,
    ) -> "_ConnectorPage": ...


class _ConnectorPage(Protocol):
    """Protocol for a page of connector configuration records."""

    @property
    def items(self) -> "tuple[_ConnectorRecord, ...]": ...


class _ConnectorRecord(Protocol):
    """Protocol for a single connector configuration record."""

    @property
    def tool_name(self) -> str: ...


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


__all__ = [
    "TenantConnectorRegistry",
    "TenantConnectorRegistryProtocol",
    "ToolRegistry",
]
