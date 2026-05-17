"""Workflow registry.

Same architectural choice as the task and provider registries:
explicit, opt-in registration at startup. Reviewers know which
workflows the process is willing to run by reading
`app/dependencies/orchestration.py`.
"""

from __future__ import annotations

from app._deprecated.orchestration.exceptions import WorkflowNotRegisteredError
from app._deprecated.orchestration.workflows.base import BaseWorkflow


class _WorkflowAlreadyRegisteredError(Exception):
    """Raised at startup if two workflows claim the same registry name."""


class WorkflowRegistry:
    """Process-wide, name-keyed map of workflows."""

    __slots__ = ("_workflows",)

    def __init__(self) -> None:
        self._workflows: dict[str, BaseWorkflow] = {}

    def register(self, workflow: BaseWorkflow) -> None:
        if not workflow.name:
            raise ValueError(f"workflow {type(workflow).__name__} has no `name`")
        if workflow.name in self._workflows:
            raise _WorkflowAlreadyRegisteredError(workflow.name)
        self._workflows[workflow.name] = workflow

    def resolve(self, name: str) -> BaseWorkflow:
        try:
            return self._workflows[name]
        except KeyError as exc:
            raise WorkflowNotRegisteredError(name) from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._workflows.keys()))

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._workflows

    def __len__(self) -> int:
        return len(self._workflows)


__all__ = ["WorkflowRegistry"]
