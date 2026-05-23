"""Worker transaction-boundary invariants."""

from __future__ import annotations

import ast
from pathlib import Path


_AGENT_TASKS = Path("apps/backend/app/workers/agent_tasks.py")
_MODEL_EXECUTION_CALLS = {
    "_generate_diagnostic_reasoning_draft",
    "generate_reasoning",
    "complete",
}


def test_diagnostic_worker_keeps_model_execution_outside_db_sessions() -> None:
    tree = ast.parse(_AGENT_TASKS.read_text(encoding="utf-8"))
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncWith):
            continue
        if not any(
            _is_session_factory_context(item.context_expr)
            for item in node.items
        ):
            continue
        if _contains_awaited_model_execution(node):
            offenders.append(node.lineno)

    assert offenders == []


def test_diagnostic_generation_helper_is_sessionless() -> None:
    tree = ast.parse(_AGENT_TASKS.read_text(encoding="utf-8"))
    helper = _function(tree, "_generate_diagnostic_reasoning_draft")

    assert helper is not None
    assert not any(isinstance(node, ast.AsyncWith) for node in ast.walk(helper))


def _function(
    tree: ast.AST,
    name: str,
) -> ast.AsyncFunctionDef | ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            if node.name == name:
                return node
    return None


def _is_session_factory_context(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "session_factory"
    )


def _contains_awaited_model_execution(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Await):
            continue
        call = child.value
        if not isinstance(call, ast.Call):
            continue
        name = _call_name(call.func)
        if name in _MODEL_EXECUTION_CALLS:
            return True
    return False


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None
