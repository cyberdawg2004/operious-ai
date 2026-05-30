"""
Architectural invariant regression tests.

These tests fail when constitutional rules are violated. They exist
because the 2026 forensic audit found 215 NO items. Every invariant
here was once a failing or manually audited rule.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import requires_postgres

APP_DIR: Final[Path] = Path("apps/backend/app")
ROUTER_DIR: Final[Path] = APP_DIR / "api" / "v1" / "routers"
BOUNDARY_DIR: Final[Path] = APP_DIR / "boundary"

_ALLOWED_ROUTER_RUNTIME_TYPE_IMPORTS: Final[dict[str, frozenset[str]]] = {
    # WebSocket voice gateway reads the app-state runtime and type-checks it
    # before handing transport frames to the voice substrate.
    "voice.py": frozenset({"VoiceCallSessionRuntime"}),
}

_NON_LINEAGE_UUID4_MARKERS: Final[tuple[str, ...]] = (
    "approved_exception",
    "envelope-local",
    "ephemeral",
    "non-lineage",
    "runtime trace",
    "test",
)


def test_routers_do_not_import_runtimes() -> None:
    """Routers must not import runtime modules directly."""

    violations: list[str] = []
    for router_file in sorted(ROUTER_DIR.glob("*.py")):
        if router_file.name == "__init__.py":
            continue
        tree = ast.parse(router_file.read_text(encoding="utf-8"))
        allowed_types = _ALLOWED_ROUTER_RUNTIME_TYPE_IMPORTS.get(
            router_file.name,
            frozenset(),
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = node.module or ""
            if module.startswith("app.") and ".runtime" in module:
                violations.append(f"{router_file.name}: imports {module!r}")
            for alias in node.names:
                name = alias.name
                if name in allowed_types or name.endswith("RuntimeError"):
                    continue
                if name.endswith("Runtime"):
                    violations.append(
                        f"{router_file.name}: imports runtime type {name!r}"
                    )

    assert not violations, (
        "Router files must not import runtimes directly:\n"
        + "\n".join(violations)
    )


def test_no_deprecated_imports() -> None:
    """The _deprecated directory is quarantined from live app code."""

    violations: list[str] = []
    for pyfile in APP_DIR.rglob("*.py"):
        if "_deprecated" in pyfile.parts:
            continue
        content = pyfile.read_text(encoding="utf-8")
        if (
            "from app._deprecated" in content
            or "import app._deprecated" in content
            or "from ._deprecated" in content
            or "import _deprecated" in content
        ):
            violations.append(str(pyfile))

    assert not violations, (
        "_deprecated imports found in live code:\n" + "\n".join(violations)
    )


@requires_postgres
@pytest.mark.asyncio
async def test_force_rls_on_all_tenant_tables(
    pg_session: AsyncSession,
) -> None:
    """Every table with tenant_id must have FORCE ROW LEVEL SECURITY."""

    result = await pg_session.execute(
        text(
            """
            SELECT
                c.relname AS tablename,
                c.relrowsecurity AS rowsecurity,
                c.relforcerowsecurity AS forcerowsecurity
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relkind = 'r'
              AND EXISTS (
                SELECT 1 FROM information_schema.columns col
                WHERE col.table_schema = 'public'
                  AND col.table_name = c.relname
                  AND col.column_name = 'tenant_id'
              )
              AND (NOT c.relrowsecurity OR NOT c.relforcerowsecurity)
            ORDER BY c.relname
            """
        )
    )
    violations = result.fetchall()

    assert not violations, (
        "Tables with tenant_id missing FORCE RLS:\n"
        + "\n".join(
            f"  {row[0]}: rowsecurity={row[1]}, forcerowsecurity={row[2]}"
            for row in violations
        )
    )


def test_celery_tasks_have_retry_settings() -> None:
    """Every Celery task must have explicit retry and delay settings."""

    from app.workers.celery_app import celery_app

    for module_name in celery_app.conf.include:
        importlib.import_module(str(module_name))

    violations: list[str] = []
    for task_name, task in celery_app.tasks.items():
        if task_name.startswith("celery."):
            continue
        max_retries = getattr(task, "max_retries", None)
        retry_delay = getattr(task, "default_retry_delay", None)
        if not isinstance(max_retries, int) or not isinstance(
            retry_delay,
            int,
        ):
            violations.append(task_name)

    assert not violations, (
        "Tasks missing explicit retry settings:\n"
        + "\n".join(f"  {task}" for task in sorted(violations))
    )


def test_channel_adapters_no_governance_import() -> None:
    """Channel adapter files are transport-only and do not import governance."""

    violations: list[str] = []
    for pyfile in BOUNDARY_DIR.rglob("*.py"):
        if "adapter" not in pyfile.name and "adapters" not in pyfile.parts:
            continue
        content = pyfile.read_text(encoding="utf-8")
        if "CROSS_SUBSTRATE_ACCEPTED" in content:
            continue
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (
                node.module or ""
            ).startswith("app.governance"):
                violations.append(str(pyfile.relative_to(APP_DIR)))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app.governance"):
                        violations.append(str(pyfile.relative_to(APP_DIR)))

    assert not violations, (
        "Channel adapters importing governance:\n"
        + "\n".join(f"  {violation}" for violation in sorted(set(violations)))
    )


def test_no_uuid4_in_lineage_modules() -> None:
    """Identity modules must document any uuid4 use as non-lineage."""

    candidates = set(APP_DIR.rglob("identity.py"))
    candidates.update(APP_DIR.rglob("identity/__init__.py"))
    violations: list[str] = []
    for pyfile in sorted(candidates):
        if "_deprecated" in pyfile.parts:
            continue
        lines = pyfile.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if "uuid4()" not in line and "uuid.uuid4()" not in line:
                continue
            prior = lines[index - 1] if index > 0 else ""
            marker_text = f"{prior} {line}".lower()
            if not any(marker in marker_text for marker in _NON_LINEAGE_UUID4_MARKERS):
                violations.append(f"{pyfile}:{index + 1}: {line.strip()}")

    assert not violations, (
        "uuid4() in identity modules without non-lineage documentation:\n"
        + "\n".join(f"  {violation}" for violation in violations)
    )


def test_router_invariants_file_exists() -> None:
    """The router invariant test suite must not be deleted."""

    test_file = Path("apps/backend/tests/test_router_invariants.py")
    assert test_file.exists(), "Router invariants test file missing"
    assert test_file.stat().st_size > 100, "Router invariants test file empty"
