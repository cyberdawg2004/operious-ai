"""Structured logging for orchestration execution.

Two emission seams the runtime calls into:

* `log_workflow_event` — one record per `WorkflowTrace`.
* `log_task_event`     — one record per `TaskTrace`.

Every record automatically carries the ambient `request_id` via the
existing `RequestContextFilter`, so orchestration runs are correlatable
with the inbound HTTP request that triggered them and with any AI
executions they fanned out into (which carry the same `request_id`).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.core.logging import get_logger
from app._deprecated.orchestration.enums import ExecutionPhase, TaskStatus, WorkflowStatus
from app._deprecated.orchestration.tracing import TaskTrace, WorkflowTrace

_workflow_logger = get_logger("orchestration.workflow")
_task_logger = get_logger("orchestration.task")


def log_workflow_event(trace: WorkflowTrace) -> None:
    """Emit one `orchestration_workflow` record for a finished workflow."""
    phase = (
        ExecutionPhase.WORKFLOW_COMPLETED
        if trace.status == WorkflowStatus.SUCCEEDED
        else ExecutionPhase.WORKFLOW_FAILED
    )
    payload: dict[str, Any] = {
        "phase": phase.value,
        "workflow_execution_id": str(trace.workflow_execution_id),
        "workflow_name": trace.workflow_name,
        "status": trace.status.value,
        "task_count": trace.task_count,
        "latency_ms": trace.latency_ms,
        "started_at": trace.started_at.isoformat(),
        "ended_at": trace.ended_at.isoformat(),
        "request_id": trace.request_id,
        "error": trace.error,
        "metadata": dict(trace.metadata),
    }
    if trace.status == WorkflowStatus.SUCCEEDED:
        _workflow_logger.info("orchestration_workflow", extra={"workflow": payload})
    else:
        _workflow_logger.warning("orchestration_workflow", extra={"workflow": payload})


def log_task_event(trace: TaskTrace) -> None:
    """Emit one `orchestration_task` record for a finished task."""
    phase = (
        ExecutionPhase.TASK_COMPLETED
        if trace.status == TaskStatus.SUCCEEDED
        else ExecutionPhase.TASK_FAILED
    )
    payload: dict[str, Any] = {
        "phase": phase.value,
        "workflow_execution_id": str(trace.workflow_execution_id),
        "task_execution_id": str(trace.task_execution_id),
        "workflow_name": trace.workflow_name,
        "task_name": trace.task_name,
        "sequence_index": trace.sequence_index,
        "status": trace.status.value,
        "latency_ms": trace.latency_ms,
        "started_at": trace.started_at.isoformat(),
        "ended_at": trace.ended_at.isoformat(),
        "request_id": trace.request_id,
        "error": trace.error,
        "metadata": dict(trace.metadata),
    }
    if trace.status == TaskStatus.SUCCEEDED:
        _task_logger.info("orchestration_task", extra={"task": payload})
    else:
        _task_logger.warning("orchestration_task", extra={"task": payload})


__all__ = ["log_workflow_event", "log_task_event"]
