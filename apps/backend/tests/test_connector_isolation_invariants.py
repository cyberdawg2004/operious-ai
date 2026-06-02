"""Connector substrate isolation invariants."""

from __future__ import annotations

from pathlib import Path

CONNECTOR_ROOT = (
    Path(__file__).resolve().parent.parent / "app" / "agents" / "tools" / "connectors"
)

_BASE_FILES = {"base.py", "config.py", "__init__.py"}
_FORBIDDEN_SUBSTRATES = (
    "app.governance",
    "app.session",
    "app.execution",
    "app.coordination",
    "app.supervisor",
    "app.supervision",
)
_FORBIDDEN_NETWORK_LIBS = ("httpx", "aiohttp", "socket", "requests")


def test_concrete_connectors_do_not_import_forbidden_substrates() -> None:
    violations: list[str] = []
    for path in _concrete_connector_files():
        for line_no, stripped in _import_lines(path):
            for forbidden in _FORBIDDEN_SUBSTRATES:
                if stripped.startswith(f"from {forbidden}") or stripped.startswith(
                    f"import {forbidden}"
                ):
                    violations.append(_violation(path, line_no, stripped))

    assert not violations, "\n".join(violations)


def test_concrete_connectors_do_not_import_network_libraries() -> None:
    violations: list[str] = []
    for path in _concrete_connector_files():
        for line_no, stripped in _import_lines(path):
            for forbidden in _FORBIDDEN_NETWORK_LIBS:
                if stripped.startswith(f"from {forbidden}") or stripped.startswith(
                    f"import {forbidden}"
                ):
                    violations.append(_violation(path, line_no, stripped))

    assert not violations, "\n".join(violations)


def _concrete_connector_files() -> list[Path]:
    return [
        path
        for path in sorted(CONNECTOR_ROOT.rglob("*.py"))
        if path.name not in _BASE_FILES and "__pycache__" not in path.parts
    ]


def _import_lines(path: Path) -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("from ") or stripped.startswith("import "):
            rows.append((line_no, stripped))
    return rows


def _violation(path: Path, line_no: int, stripped: str) -> str:
    return f"{path.relative_to(CONNECTOR_ROOT)}:{line_no}: {stripped}"
