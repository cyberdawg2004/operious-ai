"""Queue topology invariants for PR_T1.

Verifies:
1. ALL_QUEUES contains exactly the expected set of queue names.
2. No task in the worker package uses bare string queue names.
3. diagnostic.high, diagnostic.normal, diagnostic.retry appear in
   DIAGNOSTIC_QUEUE_PRIORITY in that order.
4. No task routes to the default 'celery' queue.
5. ExecutionPublisher references only queue constants.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.queues import (
    ALL_QUEUES,
    DIAGNOSTIC_QUEUE_PRIORITY,
    QUEUE_DEAD_LETTER,
    QUEUE_DIAGNOSTIC_HIGH,
    QUEUE_DIAGNOSTIC_NORMAL,
    QUEUE_DIAGNOSTIC_RETRY,
    QUEUE_SEMANTIC_QUARANTINE,
)

EXPECTED_QUEUES = {
    "ingress.email",
    "ingress.whatsapp",
    "ingress.shopify",
    "ingress.voice",
    "diagnostic.high",
    "diagnostic.normal",
    "diagnostic.retry",
    "escalation",
    "supervisor",
    "qa",
    "sop_intelligence",
    "knowledge_indexing",
    "webhook_maintenance",
    "dead_letter",
    "semantic_quarantine",
}

BACKEND_ROOT = Path(__file__).parent.parent
APP_DIR = BACKEND_ROOT / "app"
WORKER_DIR = APP_DIR / "workers"
BOUNDARY_DIR = APP_DIR / "boundary"


def test_queue_constants_live_in_neutral_app_module() -> None:
    assert (APP_DIR / "queues.py").is_file()
    assert not (WORKER_DIR / "queues.py").exists()


def test_all_queues_contains_expected_set() -> None:
    assert set(ALL_QUEUES) == EXPECTED_QUEUES, (
        f"ALL_QUEUES mismatch.\n"
        f"Missing: {EXPECTED_QUEUES - set(ALL_QUEUES)}\n"
        f"Extra: {set(ALL_QUEUES) - EXPECTED_QUEUES}"
    )


def test_diagnostic_priority_order() -> None:
    assert DIAGNOSTIC_QUEUE_PRIORITY[0] == QUEUE_DIAGNOSTIC_HIGH
    assert DIAGNOSTIC_QUEUE_PRIORITY[1] == QUEUE_DIAGNOSTIC_NORMAL
    assert DIAGNOSTIC_QUEUE_PRIORITY[2] == QUEUE_DIAGNOSTIC_RETRY


def test_no_bare_string_queue_names_in_worker() -> None:
    violations: list[str] = []
    for py_file in WORKER_DIR.rglob("*.py"):
        if py_file.name == "queues.py":
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        violations.extend(_bare_queue_string_violations(py_file, tree))
    assert not violations, (
        "Bare string queue names found:\n" + "\n".join(violations)
    )


def test_no_default_celery_queue_references() -> None:
    violations: list[str] = []
    for py_file in WORKER_DIR.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        for lineno, line in enumerate(content.splitlines(), 1):
            if re.search(r"['\"]celery['\"]", line) and (
                "queue" in line.lower() or "route" in line.lower()
            ):
                violations.append(f"{py_file}:{lineno}: {line.strip()}")
    assert not violations, (
        "Default 'celery' queue name found:\n" + "\n".join(violations)
    )


def test_no_bare_string_queue_names_in_boundary() -> None:
    if not BOUNDARY_DIR.exists():
        pytest.skip("boundary substrate not present")
    bare_pattern = re.compile(r"queue\s*=\s*['\"]")
    violations: list[str] = []
    for py_file in BOUNDARY_DIR.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        for lineno, line in enumerate(content.splitlines(), 1):
            if bare_pattern.search(line):
                violations.append(f"{py_file}:{lineno}: {line.strip()}")
    assert not violations, (
        "Bare string queue names in boundary:\n" + "\n".join(violations)
    )


def test_all_queues_has_no_duplicates() -> None:
    assert len(ALL_QUEUES) == len(set(ALL_QUEUES)), (
        "ALL_QUEUES contains duplicate entries"
    )


def test_maintenance_tasks_use_webhook_maintenance_queue() -> None:
    maintenance_files = [
        "execution_recovery_tasks.py",
        "webhook_nonce_tasks.py",
        "escalation_recovery_tasks.py",
    ]
    for filename in maintenance_files:
        filepath = WORKER_DIR / filename
        if not filepath.exists():
            continue
        content = filepath.read_text(encoding="utf-8")
        assert "QUEUE_WEBHOOK_MAINTENANCE" in content, (
            f"{filename} must use QUEUE_WEBHOOK_MAINTENANCE constant"
        )


def test_execution_publishers_reference_queue_constants() -> None:
    publisher_files = [
        APP_DIR / "execution" / "celery_publisher.py",
        APP_DIR / "escalation" / "celery_publisher.py",
    ]
    violations: list[str] = []
    for py_file in publisher_files:
        content = py_file.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(py_file))
        violations.extend(_bare_queue_string_violations(py_file, tree))
        if ".EXECUTION_QUEUE_NAME" in content or ".ESCALATION_QUEUE_NAME" in content:
            violations.append(f"{py_file}: publisher fallback must use queue constants")
    assert not violations, (
        "Publisher queue references must use constants:\n" + "\n".join(violations)
    )


def test_dead_letter_queue_constant_is_declared() -> None:
    assert QUEUE_DEAD_LETTER == "dead_letter"


def test_semantic_quarantine_queue_constant_is_declared() -> None:
    assert QUEUE_SEMANTIC_QUARANTINE == "semantic_quarantine"


def _bare_queue_string_violations(
    py_file: Path,
    tree: ast.AST,
) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "queue" and _is_string_literal(keyword.value):
                    violations.append(
                        f"{py_file}:{keyword.value.lineno}: queue uses string literal"
                    )
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if _literal_text(key) == "queue" and _is_string_literal(value):
                    violations.append(
                        f"{py_file}:{value.lineno}: queue route uses string literal"
                    )
    return violations


def _literal_text(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_string_literal(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)
