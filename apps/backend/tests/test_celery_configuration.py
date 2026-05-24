"""Celery and Redis startup configuration invariants."""

from __future__ import annotations

import ast
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from app.core.config import get_settings
from app.core.redis_policy import verify_redis_memory_policy
from app.workers.agent_tasks import execute_diagnostic_agent
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
