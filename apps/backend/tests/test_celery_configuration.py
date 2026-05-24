"""Celery and Redis startup configuration invariants."""

from __future__ import annotations

import ast
import logging
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import get_settings
from app.core.redis_policy import verify_redis_memory_policy
from app.workers.agent_tasks import (
    DiagnosticNonRetryableError,
    _DiagnosticExecutionWorkItem,
    _bounded_failure_metadata,
    _dead_letter_task_payload,
    _diagnostic_failure_is_terminal,
    _retry_countdown,
    execute_diagnostic_agent,
)
from app.workers.celery_app import celery_app
from app.workers.escalation_recovery_tasks import reconcile_stale_escalation_outbox
from app.workers.escalation_tasks import create_governance_escalation
from app.workers.execution_recovery_tasks import (
    reconcile_stale_execution_outbox,
    recover_stale_executions,
)
from app.workers.qa_tasks import score_supervisor_inspection
from app.workers.sop_intelligence_tasks import propose_sop_intelligence_change
from app.workers.supervisor_tasks import evaluate_session_supervisor
from app.workers.webhook_nonce_tasks import cleanup_expired_webhook_nonces


_BACKEND_APP_DIR = Path(__file__).parents[1] / "app"
_RESULT_READ_SCAN_DIRS = (
    _BACKEND_APP_DIR / "workers",
    _BACKEND_APP_DIR / "execution",
    _BACKEND_APP_DIR / "escalation",
    _BACKEND_APP_DIR / "coordination",
    _BACKEND_APP_DIR / "services",
)
_FIRE_AND_FORGET_TASKS = {
    "execute_diagnostic_agent": execute_diagnostic_agent,
    "evaluate_session_supervisor": evaluate_session_supervisor,
    "score_supervisor_inspection": score_supervisor_inspection,
    "propose_sop_intelligence_change": propose_sop_intelligence_change,
    "create_governance_escalation": create_governance_escalation,
    "recover_stale_executions": recover_stale_executions,
    "reconcile_stale_execution_outbox": reconcile_stale_execution_outbox,
    "reconcile_stale_escalation_outbox": reconcile_stale_escalation_outbox,
    "cleanup_expired_webhook_nonces": cleanup_expired_webhook_nonces,
}
_TASK_RETRY_BUDGETS = {
    "execute_diagnostic_agent": 3,
    "create_governance_escalation": 2,
    "evaluate_session_supervisor": 1,
    "score_supervisor_inspection": 1,
    "propose_sop_intelligence_change": 1,
    "recover_stale_executions": 5,
    "reconcile_stale_execution_outbox": 5,
    "reconcile_stale_escalation_outbox": 5,
    "cleanup_expired_webhook_nonces": 1,
}


class _ConfigRedis:
    def __init__(self, config: Mapping[str, Any]) -> None:
        self.config = config

    async def config_get(self, pattern: str = "*") -> Mapping[str, Any]:
        del pattern
        return self.config


class _RestrictedConfigRedis:
    async def config_get(self, pattern: str = "*") -> Mapping[str, Any]:
        del pattern
        raise RuntimeError("ERR unknown command 'CONFIG'")


def test_broker_connection_retry_on_startup_is_explicit() -> None:
    assert celery_app.conf.broker_connection_retry_on_startup is True


def test_celery_result_expires_is_one_hour() -> None:
    settings = get_settings()

    assert settings.CELERY_RESULT_EXPIRES_SECONDS == 3600
    assert celery_app.conf.result_expires == 3600


def test_fire_and_forget_tasks_ignore_results() -> None:
    assert celery_app.conf.task_ignore_result is True
    assert _FIRE_AND_FORGET_TASKS
    for task_name, task in _FIRE_AND_FORGET_TASKS.items():
        assert getattr(task, "ignore_result") is True, task_name


def test_celery_tasks_have_explicit_retry_budgets() -> None:
    assert set(_TASK_RETRY_BUDGETS) == set(_FIRE_AND_FORGET_TASKS)
    for task_name, expected_budget in _TASK_RETRY_BUDGETS.items():
        task = _FIRE_AND_FORGET_TASKS[task_name]

        assert getattr(task, "max_retries") == expected_budget, task_name
        assert getattr(task, "default_retry_delay") == 30, task_name


def test_diagnostic_retry_countdown_uses_exponential_backoff() -> None:
    assert _retry_countdown(_task_with_retries(0)) == 30
    assert _retry_countdown(_task_with_retries(1)) == 60
    assert _retry_countdown(_task_with_retries(2)) == 120


def test_diagnostic_exhausted_retries_are_terminal() -> None:
    assert (
        _diagnostic_failure_is_terminal(
            RuntimeError("temporary provider outage"),
            attempt_number=3,
            max_attempts=4,
        )
        is False
    )
    assert (
        _diagnostic_failure_is_terminal(
            RuntimeError("temporary provider outage"),
            attempt_number=4,
            max_attempts=4,
        )
        is True
    )


def test_diagnostic_non_retryable_errors_go_directly_to_dlq() -> None:
    assert (
        _diagnostic_failure_is_terminal(
            DiagnosticNonRetryableError("invalid durable context"),
            attempt_number=1,
            max_attempts=4,
        )
        is True
    )


def test_diagnostic_dlq_metadata_carries_traceback_and_task_payload() -> None:
    traceback_text = "Traceback (most recent call last): RuntimeError: boom"
    failure = _bounded_failure_metadata(
        RuntimeError("boom"),
        execution_id="execution-dlq",
        attempt_id="attempt-dlq",
        attempt_number=4,
        retry_requested=False,
        last_traceback=traceback_text,
    )
    work_item = _DiagnosticExecutionWorkItem(
        execution_id="execution-dlq",
        attempt_id="attempt-dlq",
        attempt_number=4,
        dispatch_id="dispatch-dlq",
        session_id="session-dlq",
        tenant_id="tenant-dlq",
        content="diagnostic content",
    )

    assert failure["attempt_count"] == 4
    assert failure["error_class"] == "RuntimeError"
    assert failure["error_message"] == "boom"
    assert failure["last_traceback"] == traceback_text
    assert _dead_letter_task_payload(work_item) == {
        "execution_id": "execution-dlq",
        "attempt_id": "attempt-dlq",
        "attempt_number": 4,
        "dispatch_id": "dispatch-dlq",
        "session_id": "session-dlq",
        "tenant_id": "tenant-dlq",
    }


def test_worker_and_publisher_paths_do_not_read_celery_results() -> None:
    violations: list[str] = []
    for directory in _RESULT_READ_SCAN_DIRS:
        for path in sorted(directory.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if _imports_async_result(node):
                    violations.append(
                        f"{path.relative_to(_BACKEND_APP_DIR)} imports AsyncResult"
                    )
                if _calls_zero_arg_get(node):
                    violations.append(
                        f"{path.relative_to(_BACKEND_APP_DIR)}:{node.lineno} calls .get()"
                    )
                if _reads_delay_result(node):
                    violations.append(
                        f"{path.relative_to(_BACKEND_APP_DIR)}:{node.lineno} "
                        "reads a task publish result"
                    )

    assert violations == []


def test_backend_container_runs_as_non_root_celery_user() -> None:
    dockerfile = Path(__file__).parents[1] / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")

    assert "addgroup --system celery" in text
    assert "adduser --system --ingroup celery celery" in text
    assert "\nUSER celery\n" in text


@pytest.mark.asyncio
async def test_redis_memory_policy_logs_ok_when_expected(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    result = await verify_redis_memory_policy(
        redis_client=_ConfigRedis({"maxmemory-policy": "allkeys-lru"}),
        expected_policy="allkeys-lru",
    )

    assert result.valid is True
    assert result.status == "ok"
    assert result.observed_policy == "allkeys-lru"
    assert "redis_memory_policy_ok" in caplog.text


@pytest.mark.asyncio
async def test_redis_memory_policy_logs_unverifiable_for_config_restriction(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)

    result = await verify_redis_memory_policy(
        redis_client=_RestrictedConfigRedis(),
        expected_policy="allkeys-lru",
    )

    assert result.valid is False
    assert result.status == "unverifiable"
    assert result.reason == "config_get_unavailable"
    assert result.observed_policy is None
    assert "redis_memory_policy_unverifiable" in caplog.text
    assert "redis_memory_policy_misconfigured" not in caplog.text


@pytest.mark.asyncio
async def test_redis_memory_policy_logs_misconfigured_for_bad_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR)

    result = await verify_redis_memory_policy(
        redis_client=_ConfigRedis({"maxmemory-policy": "noeviction"}),
        expected_policy="allkeys-lru",
    )

    assert result.valid is False
    assert result.status == "misconfigured"
    assert result.reason == "policy_mismatch"
    assert result.observed_policy == "noeviction"
    assert "redis_memory_policy_misconfigured" in caplog.text


def _imports_async_result(node: ast.AST) -> bool:
    if isinstance(node, ast.ImportFrom):
        return any(alias.name == "AsyncResult" for alias in node.names)
    if isinstance(node, ast.Import):
        return any(alias.name.endswith(".AsyncResult") for alias in node.names)
    return False


def _calls_zero_arg_get(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and not node.args
        and not node.keywords
    )


def _reads_delay_result(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "get":
        return False
    value = node.func.value
    return _is_task_publish_call(value) or (
        isinstance(value, ast.Name) and value.id.endswith("_result")
    )


def _is_task_publish_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"delay", "apply_async"}
    )


def _task_with_retries(retries: int) -> SimpleNamespace:
    return SimpleNamespace(request=SimpleNamespace(retries=retries))
