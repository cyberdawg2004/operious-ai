"""Phase 2.5-A tenant configuration layering invariants."""

from __future__ import annotations

import ast
from pathlib import Path


_BACKEND_APP = Path(__file__).parent.parent / "app"
_TENANT_ROUTER = _BACKEND_APP / "api" / "v1" / "routers" / "tenant.py"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    return modules


def test_tenant_router_does_not_access_persistence_or_runtime() -> None:
    modules = _imports(_TENANT_ROUTER)
    offenders = [
        module
        for module in modules
        if module.startswith("app.tenant.persistence")
        or module.startswith("app.tenant.runtime")
        or module.startswith("app.tenant.db")
    ]
    assert not offenders


def test_tenant_router_reaches_tenant_configuration_service_only() -> None:
    text = _TENANT_ROUTER.read_text(encoding="utf-8")
    assert "get_tenant_configuration_service" in text
    assert "PostgresTenantConfigurationRepository" not in text
    assert "InMemoryTenantConfigurationRepository" not in text
    assert "TenantConfigurationRuntime(" not in text
