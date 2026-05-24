"""Source-level identity invariants for Wedge 3."""

from __future__ import annotations

import ast
import importlib
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType

import pytest


APP_ROOT = Path(__file__).parent.parent / "app"
DEPRECATED_ROOT = APP_ROOT / "_deprecated"

_UUID4_MARKERS = ("EPHEMERAL:", "APPROVED_EXCEPTION:")
_RUNTIME_COUNTER_TOKENS = (
    "_RUNTIME_COUNTER",
    "runtime_counter",
    "RUNTIME_COUNTER",
)
_BOOT_NONCE_TOKENS = (
    "_BOOT_NONCE",
    "_RUNTIME_BOOT_ID",
    "RUNTIME_BOOT_NONCE",
)

_RUNTIME_COUNTER_GENERATORS = (
    ("app.arbitration.identity", "generate_case_id"),
    ("app.boundary.identity", "generate_event_id"),
    ("app.boundary.translation.identity", "generate_translation_id"),
    ("app.boundary.voice.identity", "generate_event_id"),
    ("app.coordination.identity", "generate_coordination_id"),
    ("app.coordination.policy.identity", "generate_policy_id"),
    ("app.coordination.topology.identity", "generate_topology_id"),
    ("app.execution.identity", "generate_execution_id"),
    ("app.governance.identity.decision_ids", "generate_decision_id"),
    ("app.governance.identity.trace_ids", "generate_trace_id"),
    ("app.session.identity", "generate_session_id"),
)


def _python_files() -> Iterable[Path]:
    for path in sorted(APP_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        if path.is_relative_to(DEPRECATED_ROOT):
            continue
        yield path


def _is_uuid4_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "uuid4"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "uuid"
    )


def test_uuid4_calls_are_marked_ephemeral_or_approved() -> None:
    violations: list[str] = []
    for path in _python_files():
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not _is_uuid4_call(node):
                continue
            line = lines[node.lineno - 1]
            if not any(marker in line for marker in _UUID4_MARKERS):
                relative = path.relative_to(APP_ROOT.parent)
                violations.append(f"{relative}:{node.lineno}: {line.strip()}")

    assert not violations, "\n".join(violations)


def test_runtime_counter_modules_have_boot_nonce() -> None:
    violations: list[str] = []
    for path in _python_files():
        source = path.read_text()
        if not any(token in source for token in _RUNTIME_COUNTER_TOKENS):
            continue
        if any(token in source for token in _BOOT_NONCE_TOKENS):
            continue

        for line_no, line in enumerate(source.splitlines(), start=1):
            if any(token in line for token in _RUNTIME_COUNTER_TOKENS):
                relative = path.relative_to(APP_ROOT.parent)
                violations.append(f"{relative}:{line_no}: {line.strip()}")

    assert not violations, "\n".join(violations)


@pytest.mark.parametrize(
    ("module_name", "generator_name"),
    _RUNTIME_COUNTER_GENERATORS,
)
def test_runtime_counter_restart_safe(
    module_name: str,
    generator_name: str,
) -> None:
    module = importlib.reload(importlib.import_module(module_name))
    id_set_1 = _generate_ids(module, generator_name)

    restarted = importlib.reload(module)
    id_set_2 = _generate_ids(restarted, generator_name)

    assert id_set_1.isdisjoint(id_set_2), (
        f"{module_name}.{generator_name} collided across simulated "
        "process restart"
    )


def _generate_ids(module: ModuleType, generator_name: str) -> set[object]:
    generator = getattr(module, generator_name)
    return {generator() for _ in range(10)}
