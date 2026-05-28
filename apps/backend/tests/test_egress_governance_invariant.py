"""PR_RT-SAFE-2 egress governance provenance invariants."""

from __future__ import annotations

import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parent.parent
APP_ROOT = BACKEND_ROOT / "app"
EGRESS_RUNTIME = APP_ROOT / "boundary" / "egress" / "runtime.py"
EGRESS_CONTRACTS = APP_ROOT / "boundary" / "contracts" / "requests.py"
EGRESS_RECORDS = APP_ROOT / "boundary" / "persistence" / "records.py"
ADAPTER_ROOT = APP_ROOT / "boundary" / "adapters"

_EGRESS_SINK_ATTRS = {
    "delete",
    "patch",
    "post",
    "put",
    "request",
    "save_egress",
    "send",
    "serialize",
}
_EGRESS_SINK_NAMES = {"egress_result_to_record"}
_GOVERNANCE_GUARD_CALLS = {"_validate_governance_allow"}


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _class_node(tree: ast.Module, class_name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    raise AssertionError(f"{class_name} not found")


def _class_has_field(node: ast.ClassDef, field_name: str) -> bool:
    for stmt in node.body:
        if isinstance(stmt, ast.AnnAssign):
            target = stmt.target
            if isinstance(target, ast.Name) and target.id == field_name:
                return True
    return False


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _is_sink_call(call: ast.Call) -> bool:
    name = _call_name(call)
    return name in _EGRESS_SINK_ATTRS or name in _EGRESS_SINK_NAMES


def _is_guard_call(call: ast.Call) -> bool:
    return _call_name(call) in _GOVERNANCE_GUARD_CALLS


def _function_text_before(
    path: Path, function: ast.AST, lineno: int
) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = getattr(function, "lineno", 1)
    return "\n".join(lines[start - 1 : lineno - 1])


def _has_prior_guard(path: Path, function: ast.AST, lineno: int) -> bool:
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if node.lineno >= lineno:
            continue
        if _is_guard_call(node):
            return True

    prior = _function_text_before(path, function, lineno)
    return (
        "governance_decision_id" in prior
        and "get_decision" in prior
        and ("ALLOW" in prior or '"allow"' in prior)
    )


def test_egress_request_and_record_carry_governance_decision_id() -> None:
    offenders: list[str] = []
    checks = (
        (
            EGRESS_CONTRACTS,
            "BoundaryEgressRequest",
            "governance_decision_id",
        ),
        (
            EGRESS_RECORDS,
            "BoundaryEgressRecord",
            "governance_decision_id",
        ),
    )
    for path, class_name, field_name in checks:
        tree = _parse(path)
        cls = _class_node(tree, class_name)
        if not _class_has_field(cls, field_name):
            offenders.append(f"{path}:{cls.lineno}: {class_name}")

    assert not offenders, (
        "egress provenance fields missing:\n" + "\n".join(offenders)
    )


def test_egress_runtime_checks_persisted_allow_before_sinks() -> None:
    tree = _parse(EGRESS_RUNTIME)
    emit = None
    validate = None
    runtime = _class_node(tree, "BoundaryEgressRuntime")
    for stmt in runtime.body:
        if isinstance(stmt, ast.AsyncFunctionDef) and stmt.name == "emit":
            emit = stmt
        if (
            isinstance(stmt, ast.AsyncFunctionDef)
            and stmt.name == "_validate_governance_allow"
        ):
            validate = stmt

    assert emit is not None, "BoundaryEgressRuntime.emit not found"
    assert validate is not None, "egress governance validator not found"

    offenders: list[str] = []
    for node in ast.walk(emit):
        if not isinstance(node, ast.Call) or not _is_sink_call(node):
            continue
        if not _has_prior_guard(EGRESS_RUNTIME, emit, node.lineno):
            offenders.append(
                f"{EGRESS_RUNTIME}:{node.lineno}: {_call_name(node)}"
            )

    validator_source = ast.get_source_segment(
        EGRESS_RUNTIME.read_text(encoding="utf-8"), validate
    )
    assert validator_source is not None
    for token in (
        "governance_decision_id",
        "get_decision",
        "_GOVERNANCE_ALLOW_DECISION",
    ):
        if token not in validator_source:
            offenders.append(
                f"{EGRESS_RUNTIME}:{validate.lineno}: missing {token}"
            )

    assert not offenders, (
        "egress sink lacks prior persisted ALLOW governance check:\n"
        + "\n".join(offenders)
    )


def test_egress_adapters_and_send_bridges_require_governance() -> None:
    offenders: list[str] = []
    for path in sorted(ADAPTER_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = _parse(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name == "BaseEgressAdapter":
                continue
            inherits_egress = any(
                isinstance(base, ast.Name) and base.id == "BaseEgressAdapter"
                for base in node.bases
            )
            if not inherits_egress:
                continue
            has_marker = any(
                isinstance(stmt, (ast.Assign, ast.AnnAssign))
                and "requires_governance_decision_id"
                in ast.unparse(stmt)
                and "True" in ast.unparse(stmt)
                for stmt in node.body
            )
            if not has_marker:
                offenders.append(
                    f"{path}:{node.lineno}: {node.name} missing "
                    "requires_governance_decision_id = True"
                )

        for function in ast.walk(tree):
            if not isinstance(
                function, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            for call in ast.walk(function):
                if not isinstance(call, ast.Call) or not _is_sink_call(call):
                    continue
                if not _has_prior_guard(path, function, call.lineno):
                    offenders.append(
                        f"{path}:{call.lineno}: {_call_name(call)} "
                        "without governance_decision_id + ALLOW guard"
                    )

    assert not offenders, (
        "egress adapter/send bridge governance violations:\n"
        + "\n".join(offenders)
    )
