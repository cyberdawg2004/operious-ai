"""Orchestration metric emission.

Today the metric stream is structured-log-shaped (`orchestration_metric`).
The shape is what matters: workflow_name, task_name, status, latency_ms.
A future Prometheus / StatsD / OTel exporter wires into these two
functions; call sites do not change.

Kept narrow on purpose: a single dimension per measurement
(workflow latency vs task latency) rather than overloaded payloads.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app._deprecated.orchestration.tracing import TaskTrace, WorkflowTrace

_logger = get_logger("orchestration.metrics")


def record_workflow(trace: WorkflowTrace) -> None:
    """Emit one workflow-shaped metric event."""
    payload: dict[str, Any] = {
        "kind": "workflow",
        "workflow_name": trace.workflow_name,
        "status": trace.status.value,
        "task_count": trace.task_count,
        "latency_ms": trace.latency_ms,
    }
    _logger.info("orchestration_metric", extra={"orchestration_metric": payload})


def record_task(trace: TaskTrace) -> None:
    """Emit one task-shaped metric event."""
    payload: dict[str, Any] = {
        "kind": "task",
        "workflow_name": trace.workflow_name,
        "task_name": trace.task_name,
        "status": trace.status.value,
        "latency_ms": trace.latency_ms,
    }
    _logger.info("orchestration_metric", extra={"orchestration_metric": payload})


__all__ = ["record_workflow", "record_task"]
