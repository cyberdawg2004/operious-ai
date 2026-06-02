"""Legacy-deletion invariants.

The old quarantine package was deleted in Spec 1e. These tests keep
that deletion durable: the package must not return, and neither app
code nor tests may import it if someone recreates it.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parent.parent
APP_ROOT = REPO_BACKEND_ROOT / "app"
DEPRECATED_ROOT = APP_ROOT / "_deprecated"
TESTS_ROOT = REPO_BACKEND_ROOT / "tests"

LEGACY_TOP_LEVEL_PACKAGE_NAMES: tuple[str, ...] = (
    "ai",
    "embeddings",
    "memory",
    "orchestration",
    "providers",
    "rag",
)


def _python_files_under(path: Path) -> list[Path]:
    return sorted(p for p in path.rglob("*.py") if p.is_file())


def _python_files_outside_deprecated() -> list[Path]:
    files: list[Path] = []
    for path in APP_ROOT.rglob("*.py"):
        if not path.is_file():
            continue
        try:
            path.relative_to(DEPRECATED_ROOT)
        except ValueError:
            files.append(path)
    return sorted(files)


def _deprecated_imports(path: Path) -> Iterable[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "app._deprecated" or alias.name.startswith(
                    "app._deprecated."
                ):
                    yield node.lineno
                if alias.name == "_deprecated" or alias.name.startswith(
                    "_deprecated."
                ):
                    yield node.lineno
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "app._deprecated" or module.startswith(
                "app._deprecated."
            ):
                yield node.lineno
            if module == "app" and any(
                alias.name == "_deprecated" for alias in node.names
            ):
                yield node.lineno
            if node.level > 0 and (
                module == "_deprecated" or module.startswith("_deprecated.")
            ):
                yield node.lineno
            if node.level > 0 and not module and any(
                alias.name == "_deprecated" for alias in node.names
            ):
                yield node.lineno


def test_deprecated_package_is_absent() -> None:
    assert not DEPRECATED_ROOT.exists(), (
        "the deleted legacy quarantine package must not be recreated: "
        f"{DEPRECATED_ROOT.relative_to(REPO_BACKEND_ROOT)}"
    )


def test_no_app_module_imports_from_deprecated() -> None:
    offences: list[str] = []
    for path in _python_files_outside_deprecated():
        for line in _deprecated_imports(path):
            offences.append(f"{path.relative_to(REPO_BACKEND_ROOT)}:{line}")
    assert not offences, (
        "constitutional code must never import from the deleted legacy "
        "quarantine; found imports at: " + ", ".join(offences)
    )


def test_no_test_module_imports_from_deprecated() -> None:
    offences: list[str] = []
    for path in _python_files_under(TESTS_ROOT):
        for line in _deprecated_imports(path):
            offences.append(f"{path.relative_to(REPO_BACKEND_ROOT)}:{line}")
    assert not offences, (
        "tests must never import from the deleted legacy quarantine; "
        "found imports at: " + ", ".join(offences)
    )


def test_legacy_top_level_packages_remain_absent() -> None:
    offenders: list[str] = []
    for legacy in LEGACY_TOP_LEVEL_PACKAGE_NAMES:
        candidate = APP_ROOT / legacy
        if candidate.exists():
            offenders.append(str(candidate.relative_to(REPO_BACKEND_ROOT)))
    assert not offenders, (
        "legacy top-level packages must remain deleted; found at: "
        + ", ".join(offenders)
    )
