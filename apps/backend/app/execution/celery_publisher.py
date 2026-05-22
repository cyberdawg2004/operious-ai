"""Celery-backed execution publisher."""

from __future__ import annotations

import os
import sys
from typing import Any, cast

from app.execution.publisher import ExecutionPublisher
from app.workers.agent_tasks import (
    execute_diagnostic_agent,
    execute_diagnostic_agent_runtime,
)


class CeleryExecutionPublisher(ExecutionPublisher):
    """Publish execution intents through the worker transport."""

    async def publish_execution(
        self,
        execution_id: str,
    ) -> None:
        task = cast(Any, execute_diagnostic_agent)
        if _running_under_pytest():
            await execute_diagnostic_agent_runtime(
                execution_id=execution_id,
            )
        else:
            task.delay(execution_id=execution_id)


def _running_under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


__all__ = ["CeleryExecutionPublisher"]
