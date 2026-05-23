"""Phase E invariant: Postgres persistence reads must be SQL-bounded."""

from __future__ import annotations

import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"


def test_no_unbounded_all_calls_in_postgres_persistence() -> None:
    offenders: list[str] = []
    for path in sorted(APP_DIR.glob("*/persistence/postgres.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        parents = _parents(tree)
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not _is_all_call(node):
                continue
            statement = _enclosing_statement(node, parents)
            segment = ast.get_source_segment(source, statement) or ""
            line = lines[node.lineno - 1]
            if ".limit(" in segment or "bounded-load-ok" in line:
                continue
            offenders.append(f"{path.relative_to(APP_DIR)}:{node.lineno}")

    assert not offenders, (
        "Postgres persistence modules must not materialize unbounded "
        f"result sets with .all(): {offenders}"
    )


def test_no_python_side_pagination_slices_in_postgres_persistence() -> None:
    offenders: list[str] = []
    for path in sorted(APP_DIR.glob("*/persistence/postgres.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        parents = _parents(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Subscript):
                continue
            if not isinstance(node.slice, ast.Slice):
                continue
            function = _enclosing_function(node, parents)
            if function is None:
                continue
            if not (
                function.name.startswith("list_")
                or function.name.startswith("query_")
            ):
                continue
            segment = ast.get_source_segment(source, node) or ""
            if "query.offset" in segment or "query.limit" in segment:
                offenders.append(
                    f"{path.relative_to(APP_DIR)}:{node.lineno}:{function.name}"
                )

    assert not offenders, (
        "Postgres list/query methods must use SQL LIMIT/OFFSET, not "
        f"Python-side slicing: {offenders}"
    )


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    result: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            result[child] = parent
    return result


def _is_all_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "all"
    )


def _enclosing_statement(
    node: ast.AST,
    parents: dict[ast.AST, ast.AST],
) -> ast.stmt:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, ast.stmt):
            return current
    raise AssertionError("call without enclosing statement")


def _enclosing_function(
    node: ast.AST,
    parents: dict[ast.AST, ast.AST],
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
    return None
