"""Static invariant: lineage substrates must not mint uuid4 IDs."""

from __future__ import annotations

import ast
from pathlib import Path


LINEAGE_ROOTS = (
    Path("apps/backend/app/boundary"),
    Path("apps/backend/app/coordination"),
    Path("apps/backend/app/governance"),
    Path("apps/backend/app/session"),
    Path("apps/backend/app/execution"),
    Path("apps/backend/app/arbitration"),
    Path("apps/backend/app/supervisor"),
    Path("apps/backend/app/runtime"),
)


def test_no_uuid4_in_lineage_paths() -> None:
    violations: list[str] = []
    for root in LINEAGE_ROOTS:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            uuid_module_names = {"uuid"}
            uuid4_names = {"uuid4"}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "uuid":
                            uuid_module_names.add(alias.asname or alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module == "uuid":
                    for alias in node.names:
                        if alias.name == "uuid4":
                            violations.append(
                                f"{path}:{node.lineno} imports uuid4 directly"
                            )
                            uuid4_names.add(alias.asname or alias.name)
                elif isinstance(node, ast.Call):
                    func = node.func
                    if (
                        isinstance(func, ast.Attribute)
                        and func.attr == "uuid4"
                        and isinstance(func.value, ast.Name)
                        and func.value.id in uuid_module_names
                    ):
                        violations.append(
                            f"{path}:{node.lineno} calls {func.value.id}.uuid4()"
                        )
                    elif isinstance(func, ast.Name) and func.id in uuid4_names:
                        violations.append(f"{path}:{node.lineno} calls uuid4()")

    assert violations == []
