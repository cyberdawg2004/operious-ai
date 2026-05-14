"""Task execution persistence.

One row per task invocation inside a workflow. References
`workflow_executions.id` via FK with `ON DELETE CASCADE`: cleaning up
a workflow row clears its task rows automatically.

`sequence_index` is a 0-based ordinal that records the task's position
in the workflow's call sequence. Combined with `workflow_execution_id`
it uniquely identifies a task invocation within a run, even when the
same task name is invoked multiple times (loops, retries inside the
workflow).

Indexed for the same operational queries the workflow table is:

* `workflow_execution_id` — "show me every task for this run"
* `task_name`             — "show me every invocation of task X"
* `status`                — "show me failed task executions"
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TaskExecution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Durable record of one task invocation."""

    __tablename__ = "task_executions"

    workflow_execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    task_name: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    sequence_index: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    latency_ms: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )

    input_payload: Mapped[dict[str, Any] | None] = mapped_column(
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


__all__ = ["TaskExecution"]
