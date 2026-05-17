"""Abstract workflow contract.

A workflow is `async def execute(payload, context, runner) -> WorkflowResult`.
That is the entire contract.

`WorkflowRunner` is a structural protocol — the runtime provides the
concrete implementation; tests provide a fake. Keeping the surface
narrow (one method) is what makes workflows trivial to unit-test
without the persistence layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Mapping, Protocol, runtime_checkable

from app._deprecated.orchestration.context import OrchestrationContext
from app._deprecated.orchestration.envelopes import TaskEnvelope
from app._deprecated.orchestration.models import WorkflowResult


@runtime_checkable
class WorkflowRunner(Protocol):
    """The runtime-provided collaborator a workflow uses to execute tasks.

    The narrow surface (one method) is the entire reason workflows are
    trivial to test in isolation — supply any object that exposes
    `run_task` and you have a fake runtime.
    """

    async def run_task(
        self,
        name: str,
        payload: Mapping[str, Any] | None = None,
    ) -> TaskEnvelope:
        ...


class BaseWorkflow(ABC):
    """Deterministic, code-driven workflow.

    Subclasses MUST:

    * set the class-level `name: str` attribute (the registry key),
    * implement `execute()` and return a `WorkflowResult` on success,
    * raise (any exception) on failure — the runtime captures the
      exception, marks the workflow failed, persists the failure, and
      surfaces a `WorkflowEnvelope(error=...)`.

    Subclasses MUST NOT:

    * import `OrchestrationRuntime` (only the `WorkflowRunner` protocol),
    * persist their own state (the runtime owns persistence),
    * emit traces (the runtime owns trace emission).
    """

    name: ClassVar[str] = ""

    @abstractmethod
    async def execute(
        self,
        payload: Mapping[str, Any],
        context: OrchestrationContext,
        runner: WorkflowRunner,
    ) -> WorkflowResult:
        """Drive task execution and return the workflow's final result."""


__all__ = ["BaseWorkflow", "WorkflowRunner"]
