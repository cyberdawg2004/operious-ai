"""Orchestration exception hierarchy.

The runtime never raises these to the caller — every entry point
returns an `Envelope` carrying the exception in its `error` field.
Workflows and tasks DO raise them, and the runtime captures the
exception into the appropriate envelope.

Two kinds of failures we deliberately distinguish from each other:

* "registry" failures (`WorkflowNotRegisteredError`,
  `TaskNotRegisteredError`) — programmer error / operational config
  drift. Worth surfacing visibly as a discrete error class.
* "execution" failures (`WorkflowExecutionError`, `TaskExecutionError`)
  — runtime saw a task or workflow raise; wraps the underlying cause
  via `__cause__`.
"""

from __future__ import annotations


class OrchestrationError(Exception):
    """Base class for every orchestration failure."""


class WorkflowNotRegisteredError(OrchestrationError):
    """Requested workflow is not present in the registry."""


class TaskNotRegisteredError(OrchestrationError):
    """Requested task is not present in the registry."""


class WorkflowExecutionError(OrchestrationError):
    """A workflow's `execute()` raised an unexpected exception.

    The original exception is available via `__cause__`.
    """


class TaskExecutionError(OrchestrationError):
    """A task's `execute()` raised an unexpected exception.

    The original exception is available via `__cause__`.
    """


__all__ = [
    "OrchestrationError",
    "WorkflowNotRegisteredError",
    "TaskNotRegisteredError",
    "WorkflowExecutionError",
    "TaskExecutionError",
]
