"""Abstract task contract.

A task is the platform's smallest unit of orchestration work. The
contract is intentionally minimal: one async method, one return shape,
one well-typed exception class. That minimalism is what keeps the
runtime able to treat every task uniformly — adding observability,
retries, or durability around tasks does not require changing tasks
themselves.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Mapping

from app._deprecated.orchestration.context import TaskContext
from app._deprecated.orchestration.models import TaskResult


class BaseTask(ABC):
    """Atomic unit of orchestration work.

    Subclasses MUST:

    * set the class-level `name: str` attribute used as the registry
      key (workflows reference tasks by this name),
    * implement `execute()` and return a `TaskResult` on success,
    * raise (any exception) on failure — the runtime captures the
      exception, marks the task failed, persists the failure, and
      surfaces a `TaskEnvelope(error=...)`.
    """

    name: ClassVar[str] = ""

    @abstractmethod
    async def execute(
        self,
        payload: Mapping[str, Any],
        context: TaskContext,
    ) -> TaskResult:
        """Execute the task.

        `payload` is the JSON-serialisable input the workflow handed to
        `runner.run_task(name, payload)`. `context` carries
        orchestration identity + the ambient request id.
        """


__all__ = ["BaseTask"]
