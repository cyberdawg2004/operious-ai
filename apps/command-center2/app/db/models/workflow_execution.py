"""Workflow execution persistence.

One row per `OrchestrationRuntime.execute_workflow` invocation.
Persisted lifecycle: rows are inserted with status='running' and
transitioned to a terminal status ('succeeded' / 'failed' / 'cancelled')
when the workflow completes. The 'pending' status in `WorkflowStatus`
is reserved for a future queued runtime; the synchronous Sprint F
runtime never writes it.

Columns are indexed for the queries we know we'll run:

* `workflow_name` — "show me every run of workflow X"
* `status`        — "show me failed runs"
* `request_id`    — "what did this HTTP request trigger"
* `started_at`    — "show me the most recent runs"

Sister table `task_executions` references this via FK with
`ON DELETE CASCADE` so cleaning up a workflow row also clears its
task rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WorkflowExecution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Durable record of one workflow execution.

    `meta` (column name: `meta`) holds workflow-supplied metadata.
    Named `meta` rather than `metadata` to avoid collision with
    SQLAlchemy's reserved `DeclarativeBase.metadata` class attribute.
    """

    __tablename__ = "workflow_executions"

    workflow_name: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )

    request_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    latency_ms: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )

    payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    output: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    error: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    meta: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )


__all__ = ["WorkflowExecution"]
