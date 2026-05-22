"""Phase 2-J canonical event fabric closure invariants.

These tests are deliberately architectural. Phase 2 adopted the
canonical event fabric through projection adapters; it must now stay
that way:

* source runtimes do not import event fabric authority;
* routers, services, and workers do not call projection bridges;
* the event fabric imports only stable vocabulary / infrastructure,
  never sibling runtime substrates;
* every Phase 2 projection bridge lives in ``app.runtime``.
"""

from __future__ import annotations

import ast
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1] / "app"


ADOPTED_SOURCE_ROOTS: frozenset[str] = frozenset(
    {
        "arbitration",
        "boundary",
        "execution",
        "governance",
        "session",
        "supervisor",
    }
)

RUNTIME_BOUNDARY_ROOTS: frozenset[str] = frozenset(
    {
        "api",
        "dependencies",
        "services",
        "workers",
    }
)

EVENT_FABRIC_ALLOWED_APP_IMPORTS: frozenset[str] = frozenset(
    {
        "app.db.base",
        "app.events",
        "app.governance.capability.acts",
        "app.governance.enums",
        "app.identity",
        "app.repositories.base",
    }
)

EXPECTED_PROJECTION_MODULES: frozenset[str] = frozenset(
    {
        "arbitration_event_projection.py",
        "boundary_event_projection.py",
        "execution_event_projection.py",
        "governance_event_projection.py",
        "session_event_projection.py",
        "supervisor_event_projection.py",
    }
)


def _python_files(root: Path) -> tuple[Path, ...]:
    if not root.exists():
        return ()
    return tuple(
        sorted(
            path
            for path in root.rglob("*.py")
            if "__pycache__" not in path.parts
        )
    )


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    return imports


def _is_module_or_child(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def _relative(path: Path) -> str:
    return str(path.relative_to(APP_ROOT))


def test_event_fabric_imports_no_sibling_runtime_substrates() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _python_files(APP_ROOT / "events"):
        external_app_imports = {
            module
            for module in _imported_modules(path)
            if module.startswith("app.")
            and not any(
                _is_module_or_child(module, allowed)
                for allowed in EVENT_FABRIC_ALLOWED_APP_IMPORTS
            )
        }
        if external_app_imports:
            offenders[_relative(path)] = sorted(external_app_imports)

    assert not offenders, (
        "canonical event fabric imported forbidden sibling substrate "
        f"modules: {offenders}"
    )


def test_source_substrates_do_not_import_event_fabric_authority() -> None:
    offenders: dict[str, list[str]] = {}
    for root_name in sorted(ADOPTED_SOURCE_ROOTS):
        for path in _python_files(APP_ROOT / root_name):
            imports = {
                module
                for module in _imported_modules(path)
                if _is_module_or_child(module, "app.events")
            }
            if imports:
                offenders[_relative(path)] = sorted(imports)

    assert not offenders, (
        "source substrates must project through app.runtime bridges, "
        f"not import event fabric directly: {offenders}"
    )


def test_transport_and_request_boundaries_do_not_import_projection_bridges() -> None:
    offenders: dict[str, list[str]] = {}
    for root_name in sorted(RUNTIME_BOUNDARY_ROOTS):
        for path in _python_files(APP_ROOT / root_name):
            imports = {
                module
                for module in _imported_modules(path)
                if module.startswith("app.runtime.")
                and module.endswith("_event_projection")
            }
            if imports:
                offenders[_relative(path)] = sorted(imports)

    assert not offenders, (
        "routers, services, dependencies, and workers must not call "
        f"event projection bridges directly: {offenders}"
    )


def test_operational_event_runtime_is_only_used_by_event_or_projection_layers() -> None:
    allowed_prefixes = (
        "events/",
        "runtime/arbitration_event_projection.py",
        "runtime/boundary_event_projection.py",
        "runtime/execution_event_projection.py",
        "runtime/governance_event_projection.py",
        "runtime/session_event_projection.py",
        "runtime/supervisor_event_projection.py",
    )
    offenders: list[str] = []
    for path in _python_files(APP_ROOT):
        rel = _relative(path)
        if rel.startswith("_deprecated/"):
            continue
        source = path.read_text(encoding="utf-8")
        if "OperationalEventRuntime" not in source:
            continue
        if not rel.startswith(allowed_prefixes):
            offenders.append(rel)

    assert not offenders, (
        "OperationalEventRuntime leaked outside event/projection layers: "
        f"{offenders}"
    )


def test_phase_2_projection_bridges_are_centralized_in_runtime_package() -> None:
    projection_modules = {
        path.name for path in _python_files(APP_ROOT / "runtime")
        if path.name.endswith("_event_projection.py")
    }
    missing = EXPECTED_PROJECTION_MODULES - projection_modules
    extra = projection_modules - EXPECTED_PROJECTION_MODULES

    assert not missing, f"missing Phase 2 projection bridge(s): {sorted(missing)}"
    assert not extra, (
        "unexpected event projection bridge(s); update Phase 2 closure "
        f"doctrine deliberately if these are legitimate: {sorted(extra)}"
    )
