"""Orchestration tracing primitives.

`WorkflowTrace` and `TaskTrace` are the durable, vendor-neutral
records of orchestration execution. They are the shape every
observability sink (logs today; metrics, replay, audit later) keys on.

The runtime is the ONLY producer of trace records; tasks and workflows
do not emit traces directly. That single producer is what guarantees
every orchestration step is observable in the same way, with the same
fields, regardless of which workflow or task ran it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.orchestration.enums import TaskStatus, WorkflowStatus


@dataclass(frozen=True, slots=True)
class TaskTrace:
    """Durable execution record for one task invocation."""

    workflow_execution_id: uuid.UUID
    task_execution_id: uuid.UUID
    workflow_name: str
    task_name: str
    sequence_index: int
    status: TaskStatus
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    request_id: str | None = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WorkflowTrace:
    """Durable execution record for one workflow run."""

    workflow_execution_id: uuid.UUID
    workflow_name: str
    status: WorkflowStatus
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    task_count: int
    request_id: str | None = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["TaskTrace", "WorkflowTrace"]
