"""Phase 2.2 — Transitional vendor SDK import-graph isolation.

`requirements.txt` keeps four packages on disk only as "transitional"
pins: `openai`, `anthropic`, `tenacity`, `backoff`. They exist solely
so that quarantined modules under `app/_deprecated/` remain
syntactically loadable as forensic dead code. The constitutional
runtime must NEVER reach them.

This test file enforces that contract at the AST level. It walks every
`.py` module under the constitutional substrates and the surrounding
infrastructure layer (api / core / db / dependencies / middleware /
observability / repositories / services) and fails if any of them
imports any of the transitional vendor SDKs — directly OR via a
sub-module.

The forbidden-distributions list from
`tests/test_forbidden_dependencies.py` is applied at this layer too:
even though those packages are no longer pinned in `requirements.txt`,
catching an attempted `import langchain` here gives a clearer
architectural error than a `ModuleNotFoundError` at runtime.

`app/_deprecated/**` is intentionally excluded — that subtree is the
designated containment zone for any code that still touches these
SDKs. The asymmetric quarantine invariants in
`tests/test_legacy_module_quarantine.py` already guarantee that no
constitutional code can reach `_deprecated/` to transitively pull a
vendor SDK in.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parent.parent
APP_ROOT = REPO_BACKEND_ROOT / "app"


# Top-level distribution names that must NEVER be imported by
# constitutional or infrastructure code. The set is the union of:
#
# * the four transitional pins (kept on disk solely for `_deprecated/`)
# * a defensive subset of the forbidden-distributions list, mapped to
#   their *import* names (PEP 503 distribution name → top-level Python
#   package name; the two are usually but not always identical).
_FORBIDDEN_TOPLEVEL_IMPORTS: frozenset[str] = frozenset(
    {
        # Transitional vendor SDKs.
        "openai",
        "anthropic",
        "tenacity",
        "backoff",
        # Defensive: catch any future re-introduction of the
        # forbidden ecosystems before they reach `requirements.txt`.
        "langchain",
        "langchain_core",
        "langchain_protocol",
        "langgraph",
        "langgraph_checkpoint",
        "langgraph_prebuilt",
        "langgraph_sdk",
        "langsmith",
        "crewai",
        "instructor",
        "mcp",
        "chromadb",
        "lancedb",
        "pyiceberg",
        "kubernetes",
        "supabase",
        "supabase_auth",
        "supabase_functions",
        "postgrest",
        "realtime",
        "storage3",
        "posthog",
    }
)


# Subtrees of `apps/backend/app/` whose import graph must satisfy the
# isolation invariant. `_deprecated` is intentionally OUT — it's the
# containment zone — and `__pycache__` is OUT for obvious reasons.
_GUARDED_PACKAGES: tuple[str, ...] = (
    "agents",
    "api",
    "arbitration",
    "boundary",
    "coordination",
    "core",
    "db",
    "dependencies",
    "governance",
    "hardening",
    "middleware",
    "observability",
    "organizational_intelligence",
    "repositories",
    "services",
    "session",
    "supervisor",
)


def _iter_guarded_python_files() -> Iterable[Path]:
    for package in _GUARDED_PACKAGES:
        package_dir = APP_ROOT / package
        if not package_dir.exists():
            continue
        for path in package_dir.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            yield path
    # Also scan top-level modules (`app/main.py`, `app/__init__.py`)
    # but not the `_deprecated/` subtree.
    for path in APP_ROOT.glob("*.py"):
        yield path


def _module_root(name: str) -> str:
    """Return the top-level package of a dotted import name."""
    return name.split(".", 1)[0]


def _imports_from_module(tree: ast.AST) -> Iterable[str]:
    """Yield the top-level package name for every `import ...` and
    `from ... import ...` statement in the AST. Relative imports
    (level >= 1) are ignored — they cannot reach external SDKs.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield _module_root(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue
            if node.module is None:
                continue
            yield _module_root(node.module)


def test_no_constitutional_module_imports_a_transitional_vendor_sdk() -> None:
    violations: list[str] = []
    for path in _iter_guarded_python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:  # pragma: no cover - defensive
            violations.append(
                f"{path.relative_to(REPO_BACKEND_ROOT)}: syntax error {exc!r}"
            )
            continue
        for top in _imports_from_module(tree):
            if top in _FORBIDDEN_TOPLEVEL_IMPORTS:
                violations.append(
                    f"{path.relative_to(REPO_BACKEND_ROOT)} imports `{top}` "
                    "— forbidden in constitutional / infrastructure code"
                )
    assert not violations, (
        "Phase 2.2 vendor-SDK isolation broken:\n  - "
        + "\n  - ".join(sorted(set(violations)))
    )


def test_guarded_packages_actually_exist_on_disk() -> None:
    """Smoke check so that a future rename of a substrate does not
    silently void the isolation guarantee for that substrate."""
    missing = [pkg for pkg in _GUARDED_PACKAGES if not (APP_ROOT / pkg).exists()]
    # Every constitutional substrate that exists today is listed; if a
    # substrate is renamed or removed, this test fails fast and the
    # author must update `_GUARDED_PACKAGES` deliberately.
    assert not missing, (
        "guarded packages declared in test but missing from app/: "
        + ", ".join(missing)
    )
