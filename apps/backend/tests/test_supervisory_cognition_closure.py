"""Phase 3-E supervisory cognition closure invariants.

This file locks Phase 3 into its intended authority shape:

* supervisor reconstructs from persistence and does not import live
  execution runtime authority;
* QA writes only QA scores;
* autonomous escalation work creates queue records only;
* SOP intelligence proposes approval records only and never mutates
  tenant knowledge documents;
* request-path code does not call supervisory cognition worker tasks;
* pending SOP approval proposals have no SOP Intelligence application path.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app.escalation.runtime import EscalationAgentRuntime
from app.sop_intelligence.persistence.repository import (
    SOPApprovalPersistenceProtocol,
)
from app.sop_intelligence.runtime import SOPIntelligenceRuntime
from app.workers.escalation_tasks import (
    create_governance_escalation_runtime,
)
from app.workers.qa_tasks import score_supervisor_inspection_runtime
from app.workers.sop_intelligence_tasks import (
    propose_sop_intelligence_change_runtime,
)
from app.workers.supervisor_tasks import evaluate_session_supervisor_runtime


APP_ROOT = Path(__file__).resolve().parents[1] / "app"

SUPERVISORY_SOURCE_ROOTS = (
    "supervisor",
    "qa",
    "escalation",
    "sop_intelligence",
)
REQUEST_PATH_ROOTS = (
    "api",
    "dependencies",
    "services",
)
SUPERVISORY_WORKER_MODULES = {
    "supervisor_tasks.py": "evaluate_session_supervisor",
    "qa_tasks.py": "score_supervisor_inspection",
    "escalation_tasks.py": "create_governance_escalation",
    "sop_intelligence_tasks.py": "propose_sop_intelligence_change",
}


def _python_files(root: Path) -> tuple[Path, ...]:
    if not root.exists():
        return ()
    return tuple(
        sorted(
            path
            for path in root.rglob("*.py")
            if "__pycache__" not in path.parts
        )
    )


def _relative(path: Path) -> str:
    return str(path.relative_to(APP_ROOT))


def _imported_modules(path: Path) -> list[tuple[str, tuple[str, ...]]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[tuple[str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((alias.name, ()) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.append(
                (node.module, tuple(alias.name for alias in node.names))
            )
    return imports


def _is_module_or_child(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def test_supervisor_does_not_import_execution_runtime_authority() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _python_files(APP_ROOT / "supervisor"):
        violations: list[str] = []
        text = path.read_text(encoding="utf-8")
        for module, names in _imported_modules(path):
            if _is_module_or_child(module, "app.execution.runtime"):
                violations.append(module)
            if module == "app.execution" and "ExecutionRuntime" in names:
                violations.append("app.execution.ExecutionRuntime")
        if "ExecutionRuntime" in text or "PostgresExecutionPersistence" in text:
            violations.append("live execution runtime token")
        if violations:
            offenders[_relative(path)] = sorted(set(violations))

    assert not offenders, (
        "supervisor may read execution persistence records, but must not "
        f"import live execution runtime authority: {offenders}"
    )


def test_qa_agent_writes_only_qa_score_records() -> None:
    forbidden_imports = (
        "app.session",
        "app.execution",
        "app.governance",
    )
    forbidden_write_tokens = (
        "save_session",
        "save_event",
        "request_diagnostic_execution",
        "claim_outbox_for_execution",
        "mark_outbox_",
        "record_decision",
        "record_trace",
        "record_enforcement_action",
    )
    offenders: dict[str, list[str]] = {}
    for path in _python_files(APP_ROOT / "qa"):
        violations: list[str] = []
        text = path.read_text(encoding="utf-8")
        for module, _names in _imported_modules(path):
            if any(
                _is_module_or_child(module, forbidden)
                for forbidden in forbidden_imports
            ):
                violations.append(module)
        for token in forbidden_write_tokens:
            if token in text:
                violations.append(token)
        if violations:
            offenders[_relative(path)] = sorted(set(violations))

    assert not offenders, (
        "QA agent must only write QAScoreRecord rows and must not write "
        f"session, execution, or governance records: {offenders}"
    )


def test_autonomous_escalation_agent_creates_records_only() -> None:
    create_source = inspect.getsource(
        EscalationAgentRuntime.create_for_governance_denial
    )
    worker_source = (
        APP_ROOT / "workers" / "escalation_tasks.py"
    ).read_text(encoding="utf-8")
    forbidden_tokens = (
        "approve_escalation",
        "reject_escalation",
        "update_escalation",
        "record_decision",
        "record_trace",
        "record_enforcement_action",
    )

    create_offenders = [
        token for token in forbidden_tokens if token in create_source
    ]
    worker_offenders = [
        token for token in forbidden_tokens if token in worker_source
    ]

    assert not create_offenders, (
        "create_for_governance_denial must create pending queue records "
        f"only: {create_offenders}"
    )
    assert not worker_offenders, (
        "escalation Celery task must not autonomously resolve or override "
        f"escalations: {worker_offenders}"
    )


def test_sop_intelligence_does_not_mutate_tenant_knowledge_documents() -> None:
    forbidden_tokens = (
        "create_knowledge_document",
        "save_knowledge_document",
        "update_knowledge_document",
        "update(TenantKnowledgeDocumentRow",
        "delete(TenantKnowledgeDocumentRow",
        "TenantKnowledgeDocumentRow(",
    )
    offenders: dict[str, list[str]] = {}
    for path in _python_files(APP_ROOT / "sop_intelligence"):
        text = path.read_text(encoding="utf-8")
        violations = [token for token in forbidden_tokens if token in text]
        if violations:
            offenders[_relative(path)] = violations

    assert not offenders, (
        "SOP intelligence may read tenant knowledge documents but must "
        f"not mutate them directly: {offenders}"
    )


def test_request_path_does_not_call_supervisory_cognition_workers() -> None:
    forbidden_modules = ("app.workers",)
    forbidden_call_tokens = (
        "evaluate_session_supervisor",
        "score_supervisor_inspection",
        "create_governance_escalation",
        "propose_sop_intelligence_change",
        "evaluate_session(",
        "score_inspection(",
        "create_for_governance_denial(",
        "propose_for_session(",
    )
    offenders: dict[str, list[str]] = {}
    for root_name in REQUEST_PATH_ROOTS:
        for path in _python_files(APP_ROOT / root_name):
            violations: list[str] = []
            text = path.read_text(encoding="utf-8")
            for module, _names in _imported_modules(path):
                if any(
                    _is_module_or_child(module, forbidden)
                    for forbidden in forbidden_modules
                ):
                    violations.append(module)
            for token in forbidden_call_tokens:
                if token in text:
                    violations.append(token)
            if violations:
                offenders[_relative(path)] = sorted(set(violations))

    assert not offenders, (
        "request-path code must hydrate/read or enqueue only; supervisory "
        f"cognition worker entrypoints cannot run inline: {offenders}"
    )


def test_supervisory_cognition_workers_are_registered_celery_tasks() -> None:
    celery_app_source = (
        APP_ROOT / "workers" / "celery_app.py"
    ).read_text(encoding="utf-8")
    missing: list[str] = []
    for module_name, task_name in SUPERVISORY_WORKER_MODULES.items():
        source = (APP_ROOT / "workers" / module_name).read_text(
            encoding="utf-8"
        )
        if "@celery_app.task" not in source:
            missing.append(f"{module_name}: decorator")
        if f'name="{task_name}"' not in source:
            missing.append(f"{module_name}: task name {task_name}")
        import_path = f"app.workers.{module_name.removesuffix('.py')}"
        if import_path not in celery_app_source:
            missing.append(f"celery_app include: {import_path}")

    assert not missing, (
        "supervisory cognition work must stay behind Celery transport: "
        f"{missing}"
    )


def test_supervisory_cognition_worker_entrypoints_accept_primitive_lineage() -> None:
    expected = {
        evaluate_session_supervisor_runtime: ("session_id", "tenant_id"),
        score_supervisor_inspection_runtime: ("inspection_id", "tenant_id"),
        create_governance_escalation_runtime: (
            "governance_decision_id",
            "tenant_id",
            "session_id",
        ),
        propose_sop_intelligence_change_runtime: (
            "session_id",
            "tenant_id",
            "inspection_id",
        ),
    }
    for fn, parameter_names in expected.items():
        signature = inspect.signature(fn)
        assert tuple(signature.parameters) == parameter_names


def test_sop_intelligence_approval_records_have_no_direct_application_path() -> None:
    persistence_methods = {
        name
        for name in dir(SOPApprovalPersistenceProtocol)
        if not name.startswith("_")
    }
    runtime_methods = {
        name
        for name, member in inspect.getmembers(
            SOPIntelligenceRuntime,
            predicate=inspect.iscoroutinefunction,
        )
        if not name.startswith("_")
    }
    applied_usages: dict[str, list[str]] = {}
    for path in _python_files(APP_ROOT / "sop_intelligence"):
        if path.name == "enums.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        hits: list[str] = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "APPLIED"
            ):
                hits.append("ApprovalStatus.APPLIED")
        if hits:
            applied_usages[_relative(path)] = hits

    assert persistence_methods == {
        "create_approval_record",
        "update_approval_record",
        "get_approval_record",
        "list_approval_records",
    }
    assert runtime_methods == {
        "get_approval_record",
        "list_approval_records",
        "propose_for_session",
    }
    assert not applied_usages, (
        "Phase 3-D may define the applied status for future lifecycle, "
        "but no Phase 3 code may transition pending_review proposals "
        f"to applied: {applied_usages}"
    )
