"""Persistence access for task execution rows.

Owns every query that touches `task_executions`. Same architectural
discipline as the workflow repository: intent-named methods, no
commits, no rollbacks.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Mapping, Sequence

from sqlalchemy import select, update

from app.db.models.task_execution import TaskExecution
from app.orchestration.enums import TaskStatus
from app.repositories.base import BaseRepository


class TaskExecutionRepository(BaseRepository):
    """Queries for the `task_executions` table."""

    async def start_task(
        self,
        *,
        workflow_execution_id: uuid.UUID,
        task_name: str,
        sequence_index: int,
        input_payload: Mapping[str, Any] | None,
        started_at: datetime,
    ) -> TaskExecution:
        """Insert a fresh row in the `running` state. Does NOT commit."""
        entity = TaskExecution(
            workflow_execution_id=workflow_execution_id,
            task_name=task_name,
            sequence_index=sequence_index,
            status=TaskStatus.RUNNING.value,
            started_at=started_at,
            input_payload=(
                dict(input_payload) if input_payload is not None else None
            ),
        )
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def complete_task(
        self,
        *,
        task_execution_id: uuid.UUID,
        status: TaskStatus,
        ended_at: datetime,
        latency_ms: float,
        output: Mapping[str, Any] | None,
        meta: Mapping[str, Any] | None,
        error: str | None,
    ) -> None:
        """Transition a task row to a terminal status. Does NOT commit."""
        await self.session.execute(
            update(TaskExecution)
            .where(TaskExecution.id == task_execution_id)
            .values(
                status=status.value,
                ended_at=ended_at,
                latency_ms=latency_ms,
                output=dict(output) if output is not None else None,
                meta=dict(meta) if meta is not None else None,
                error=error,
            )
        )

    async def for_workflow(
        self,
        workflow_execution_id: uuid.UUID,
    ) -> Sequence[TaskExecution]:
        """Return every task row for a given workflow run, in order."""
        stmt = (
            select(TaskExecution)
            .where(TaskExecution.workflow_execution_id == workflow_execution_id)
            .order_by(TaskExecution.sequence_index.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


__all__ = ["TaskExecutionRepository"]
