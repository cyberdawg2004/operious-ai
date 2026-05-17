"""Persistence access for workflow execution rows.

Owns every query that touches `workflow_executions`. Methods are
intent-named (`start_workflow`, `complete_workflow`, `fail_workflow`)
so the runtime reads as orchestration rather than as a thin SQL
re-export.

Repositories MUST NOT commit or rollback — the runtime owns
transaction boundaries (one short transaction per checkpoint, so
partial progress is durable on disk if the process crashes mid-run).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Mapping, Sequence

from sqlalchemy import select, update

from app._deprecated.db.models.workflow_execution import WorkflowExecution
from app._deprecated.orchestration.enums import WorkflowStatus
from app.repositories.base import BaseRepository


class WorkflowExecutionRepository(BaseRepository):
    """Queries for the `workflow_executions` table."""

    async def start_workflow(
        self,
        *,
        workflow_name: str,
        request_id: str | None,
        payload: Mapping[str, Any] | None,
        meta: Mapping[str, Any] | None,
        started_at: datetime,
    ) -> WorkflowExecution:
        """Insert a fresh row in the `running` state. Does NOT commit."""
        entity = WorkflowExecution(
            workflow_name=workflow_name,
            status=WorkflowStatus.RUNNING.value,
            request_id=request_id,
            started_at=started_at,
            payload=dict(payload) if payload is not None else None,
            meta=dict(meta) if meta is not None else None,
        )
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def complete_workflow(
        self,
        *,
        workflow_execution_id: uuid.UUID,
        status: WorkflowStatus,
        ended_at: datetime,
        latency_ms: float,
        output: Mapping[str, Any] | None,
        error: str | None,
    ) -> None:
        """Transition a row to a terminal status. Does NOT commit."""
        await self.session.execute(
            update(WorkflowExecution)
            .where(WorkflowExecution.id == workflow_execution_id)
            .values(
                status=status.value,
                ended_at=ended_at,
                latency_ms=latency_ms,
                output=dict(output) if output is not None else None,
                error=error,
            )
        )

    async def fail_unregistered(
        self,
        *,
        workflow_name: str,
        request_id: str | None,
        payload: Mapping[str, Any] | None,
        meta: Mapping[str, Any] | None,
        error: str,
        started_at: datetime,
        ended_at: datetime,
        latency_ms: float,
    ) -> WorkflowExecution:
        """Insert a row already in `failed` state.

        Used when the workflow name does not resolve in the registry —
        we still want operational visibility that someone tried to
        invoke a workflow we don't know about.
        """
        entity = WorkflowExecution(
            workflow_name=workflow_name,
            status=WorkflowStatus.FAILED.value,
            request_id=request_id,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            payload=dict(payload) if payload is not None else None,
            meta=dict(meta) if meta is not None else None,
            error=error,
        )
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def get(
        self,
        workflow_execution_id: uuid.UUID,
    ) -> WorkflowExecution | None:
        """Return one row by id, or `None`."""
        return await self.session.get(WorkflowExecution, workflow_execution_id)

    async def recent(self, *, limit: int = 50) -> Sequence[WorkflowExecution]:
        """Return the most recent workflow runs, newest first."""
        stmt = (
            select(WorkflowExecution)
            .order_by(WorkflowExecution.started_at.desc().nullslast())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


__all__ = ["WorkflowExecutionRepository"]
