"""Orchestration request-scope context.

Two context types, layered:

* `OrchestrationContext` — handed to a workflow. Identifies which
  workflow execution is in flight, carries the `request_id` from the
  ambient HTTP request (or a caller-supplied override), and hosts
  free-form `metadata` propagated into traces.

* `TaskContext` — handed to a task. Embeds the orchestration context
  AND adds task identity (`task_execution_id`, `task_name`,
  `sequence_index`). The task only needs to know about *itself*; the
  embedded orchestration context is for things like attaching the
  workflow id onto downstream AI calls.

Both are frozen — tasks do not mutate orchestration state, only
return results.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class OrchestrationContext:
    """Per-workflow-execution context."""

    workflow_execution_id: uuid.UUID
    workflow_name: str
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TaskContext:
    """Per-task-invocation context."""

    orchestration: OrchestrationContext
    task_execution_id: uuid.UUID
    task_name: str
    sequence_index: int


__all__ = ["OrchestrationContext", "TaskContext"]
