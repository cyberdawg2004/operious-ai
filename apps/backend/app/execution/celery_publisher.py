"""Celery-backed execution publisher."""

from __future__ import annotations

from typing import Any, cast

from app.execution.publisher import ExecutionPublisher
from app.workers.agent_tasks import execute_diagnostic_agent


class CeleryExecutionPublisher(ExecutionPublisher):
    """Publish execution intents through the worker transport."""

    async def publish_diagnostic_execution(
        self,
        dispatch_id: str,
        session_id: str,
        tenant_id: str,
    ) -> None:
        task = cast(Any, execute_diagnostic_agent)
        task.delay(
            dispatch_id=dispatch_id,
            session_id=session_id,
            tenant_id=tenant_id,
        )


__all__ = ["CeleryExecutionPublisher"]
