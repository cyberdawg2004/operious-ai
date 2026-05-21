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

    async def publish_diagnostic_execution(
        self,
        dispatch_id: str,
        session_id: str,
        tenant_id: str,
    ) -> None:
        task = cast(Any, execute_diagnostic_agent)
        kwargs = {
            "dispatch_id": dispatch_id,
            "session_id": session_id,
            "tenant_id": tenant_id,
        }
        if _running_under_pytest():
            await execute_diagnostic_agent_runtime(
                dispatch_id=dispatch_id,
                session_id=session_id,
                tenant_id=tenant_id,
            )
        else:
            task.delay(**kwargs)


def _running_under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


__all__ = ["CeleryExecutionPublisher"]
