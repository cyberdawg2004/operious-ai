"""Tenant topology runtime composition bridge.

Tenant configuration owns the durable DAG declaration. Coordination
topology owns structural dispatch evaluation. This module sits in
``app.runtime`` as the composition bridge between the two substrates.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.coordination.topology.evaluators.builtin import (
    AllowedPathEvaluator,
    BoundaryIsolationEvaluator,
    ChainDepthEvaluator,
    EscalationPathEvaluator,
)
from app.coordination.topology.models.topology import CoordinationTopology
from app.coordination.topology.persistence.memory import (
    InMemoryCoordinationTopologyPersistence,
)
from app.coordination.topology.registry.registry import (
    CoordinationTopologyRegistry,
)
from app.coordination.topology.runtime.runtime import (
    CoordinationTopologyRuntime,
)
from app.tenant.runtime import TenantConfigurationRuntime


@dataclass(frozen=True, slots=True)
class TenantCoordinationTopologyRuntimeProvider:
    """Build request-scoped topology runtimes from tenant configuration."""

    tenant_configuration_runtime: TenantConfigurationRuntime

    async def for_tenant(
        self,
        tenant_id: str,
    ) -> CoordinationTopologyRuntime | None:
        topology = (
            await self.tenant_configuration_runtime.load_active_coordination_topology(
                tenant_id=tenant_id,
            )
        )
        if topology is None:
            return None
        return build_coordination_topology_runtime(topology)


def build_coordination_topology_runtime(
    topology: CoordinationTopology,
) -> CoordinationTopologyRuntime:
    registry = CoordinationTopologyRegistry()
    for evaluator in (
        AllowedPathEvaluator(topology),
        BoundaryIsolationEvaluator(topology),
        ChainDepthEvaluator(topology),
        EscalationPathEvaluator(topology),
    ):
        registry.register(evaluator)
    return CoordinationTopologyRuntime(
        topology=topology,
        registry=registry,
        persistence=InMemoryCoordinationTopologyPersistence(),
    )


__all__ = [
    "TenantCoordinationTopologyRuntimeProvider",
    "build_coordination_topology_runtime",
]
