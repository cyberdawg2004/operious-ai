"""Orchestration execution envelopes.

Mirrors the AI gateway's envelope contract: every entry point of the
orchestration runtime returns an envelope. The trace is always
present; the result and the error are mutually exclusive.

Why this shape:

* Workflows that fan out to multiple tasks can collect every
  `TaskEnvelope` and inspect each trace, without per-task try/except.
* The runtime can be invoked from background callers (future schedulers,
  governance pipelines) that have no exception-handling path —
  envelopes make every outcome explicit data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Tuple, TypeVar

from app.orchestration.exceptions import OrchestrationError
from app.orchestration.models import TaskResult, WorkflowResult
from app.orchestration.tracing import TaskTrace, WorkflowTrace

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class TaskEnvelope:
    """Result-or-error wrapper around one task invocation."""

    trace: TaskTrace
    result: TaskResult | None = None
    error: OrchestrationError | None = None

    @property
    def is_ok(self) -> bool:
        return self.error is None and self.result is not None

    def unwrap(self) -> TaskResult:
        if self.error is not None:
            raise self.error
        if self.result is None:  # pragma: no cover — invariant violation
            raise RuntimeError("task envelope has neither result nor error")
        return self.result


@dataclass(frozen=True, slots=True)
class WorkflowEnvelope:
    """Result-or-error wrapper around one workflow execution.

    `task_envelopes` is the ordered tuple of every task the workflow
    actually invoked. Useful for replay, debugging, and analytics —
    callers who only care about the final result use `result`, but the
    full execution shape is always available.
    """

    trace: WorkflowTrace
    result: WorkflowResult | None = None
    error: OrchestrationError | None = None
    task_envelopes: Tuple[TaskEnvelope, ...] = field(default_factory=tuple)

    @property
    def is_ok(self) -> bool:
        return self.error is None and self.result is not None

    def unwrap(self) -> WorkflowResult:
        if self.error is not None:
            raise self.error
        if self.result is None:  # pragma: no cover — invariant violation
            raise RuntimeError("workflow envelope has neither result nor error")
        return self.result


__all__ = ["TaskEnvelope", "WorkflowEnvelope"]
