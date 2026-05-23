"""Orchestration taxonomies.

Persisted as strings (column type: `String(32)`) so that:

* SQL queries / dashboards stay readable without joining a lookup table
* migrations don't need a Postgres ENUM type (cheaper rollback)
* future analytics tools can `GROUP BY status` without metadata

The values here are the durable contract — once an enum value is in
production rows, removing it is a migration. Add freely; remove rarely.
"""

from __future__ import annotations

from enum import Enum


class WorkflowStatus(str, Enum):
    """Lifecycle states a workflow execution can be in."""

    PENDING = "pending"      # reserved for a future queued runtime
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"  # reserved for future cooperative cancellation


class TaskStatus(str, Enum):
    """Lifecycle states a task execution can be in."""

    PENDING = "pending"      # reserved
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"      # workflow chose not to execute this branch


class ExecutionPhase(str, Enum):
    """Phase tag attached to orchestration trace events.

    Mirrors the lifecycle but flattens workflow + task transitions onto
    one axis so observability sinks can filter / order events without
    cross-referencing both enums.
    """

    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"


__all__ = ["WorkflowStatus", "TaskStatus", "ExecutionPhase"]
