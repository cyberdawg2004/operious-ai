"""Phase 4 closure gate invariants.

Phase 4 closed arbitration and multi-agent coordination hardening. This
file pins the closure conditions in one place so future wedges cannot
silently loosen the contract while editing lower-level substrate tests.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path

import pytest

from app.coordination.topology.enums import TopologyEdgeKind, TopologyNodeKind
from app.coordination.topology.identity import (
    derive_edge_id,
    derive_node_id,
    derive_topology_id,
)
from app.coordination.topology.models.edge import CoordinationEdge
from app.coordination.topology.models.node import CoordinationNode
from app.coordination.topology.models.topology import CoordinationTopology
from app.runtime.dispatch_arbitration import DispatchArbitrationRuntime
from app.tenant.enums import TenantTopologyStatus
from app.tenant.exceptions import TenantTopologyCycleError
from app.tenant.persistence import InMemoryTenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime

_APP_DIR = Path("apps/backend/app")
_ARBITRATION_DIR = _APP_DIR / "arbitration"
_AGENTS_DIR = _APP_DIR / "agents"
_DISPATCH_ARBITRATION_FILE = _APP_DIR / "runtime" / "dispatch_arbitration.py"
_DISPATCH_SERVICE_FILE = _APP_DIR / "services" / "dispatch_service.py"


def test_no_direct_concrete_agent_to_agent_imports() -> None:
    concrete_agent_modules = _concrete_agent_modules()
    offenders: list[str] = []
    for path in _AGENTS_DIR.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        current_module = _module_name(path)
        for imported in _imported_modules(path):
            if imported in concrete_agent_modules and imported != current_module:
                offenders.append(f"{current_module} imports concrete agent {imported}")

    assert not offenders, (
        "Concrete agents must not import each other directly; route "
        f"handoffs through coordination topology. Offenders: {offenders}"
    )


def test_arbitration_substrate_has_no_business_runtime_imports() -> None:
    forbidden_prefixes = (
        "app.boundary",
        "app.execution",
        "app.services",
        "app.session",
        "app.workers",
    )
    offenders: list[str] = []
    for path in _ARBITRATION_DIR.rglob("*.py"):
        for imported in _imported_modules(path):
            if imported.startswith(forbidden_prefixes):
                offenders.append(f"{path}: {imported}")

    assert not offenders, (
        "Arbitration is a conflict resolver only; it must not import "
        f"business/runtime execution surfaces: {offenders}"
    )


def test_dispatch_arbitration_facade_exposes_only_evaluate() -> None:
    public_methods = {
        name
        for name, _ in inspect.getmembers(
            DispatchArbitrationRuntime,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }
    assert public_methods == {"evaluate"}


def test_dispatch_arbitration_deadlock_has_no_retry_loop() -> None:
    source = textwrap.dedent(inspect.getsource(DispatchArbitrationRuntime.evaluate))
    tree = ast.parse(source)
    loops = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While))
    ]
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "evaluate"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "_arbitration_runtime"
    ]

    assert not loops
    assert len(calls) == 1


def test_deadlock_halt_precedes_session_and_execution_creation() -> None:
    source = _DISPATCH_SERVICE_FILE.read_text(encoding="utf-8")
    halt_index = source.index("if arbitration.should_halt:")
    session_index = source.index("SessionRuntime(")
    execution_index = source.index("request_diagnostic_execution")

    assert halt_index < session_index < execution_index


@pytest.mark.asyncio
async def test_tenant_topology_cycle_detection_is_closure_pinned() -> None:
    runtime = TenantConfigurationRuntime(
        repository=InMemoryTenantConfigurationRepository(),
    )
    with pytest.raises(TenantTopologyCycleError):
        await runtime.configure_topology(
            tenant_id="tenant-phase-4-closure",
            topology=_cyclic_topology(),
            topology_name="closure-cycle",
            status=TenantTopologyStatus.ACTIVE,
            configured_by="principal:closure",
        )


def test_dispatch_arbitration_facade_does_not_project_events_directly() -> None:
    source = _DISPATCH_ARBITRATION_FILE.read_text(encoding="utf-8")
    assert "from app.events" not in source
    assert "OperationalEventRuntime" not in source
    assert "project_evaluation(" in source


def _concrete_agent_modules() -> set[str]:
    modules: set[str] = set()
    for path in _AGENTS_DIR.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if (
                isinstance(node, ast.ClassDef)
                and node.name.endswith("Agent")
                and node.name not in ("BaseAgent", "BaseGovernedLLMAgent")
            ):
                modules.add(_module_name(path))
    return modules


def _module_name(path: Path) -> str:
    relative = path.relative_to(_APP_DIR.parent).with_suffix("")
    return ".".join(relative.parts)


def _imported_modules(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.append(node.module)
    return tuple(imports)


def _cyclic_topology() -> CoordinationTopology:
    first = CoordinationNode(
        node_id=derive_node_id(seed="phase-4-closure:first"),
        participant_id="agent:phase-4-closure-first",
        kind=TopologyNodeKind.AGENT,
    )
    second = CoordinationNode(
        node_id=derive_node_id(seed="phase-4-closure:second"),
        participant_id="agent:phase-4-closure-second",
        kind=TopologyNodeKind.AGENT,
    )
    return CoordinationTopology(
        topology_id=derive_topology_id(seed="phase-4-closure:cycle"),
        name="phase-4-closure-cycle",
        nodes=(first, second),
        edges=(
            CoordinationEdge(
                edge_id=derive_edge_id(seed="phase-4-closure:first-second"),
                source_node_id=first.node_id,
                target_node_id=second.node_id,
                kind=TopologyEdgeKind.HANDOFF,
            ),
            CoordinationEdge(
                edge_id=derive_edge_id(seed="phase-4-closure:second-first"),
                source_node_id=second.node_id,
                target_node_id=first.node_id,
                kind=TopologyEdgeKind.HANDOFF,
            ),
        ),
    )
