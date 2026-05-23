"""Task registry.

A name-keyed map of `BaseTask` instances, populated explicitly at
startup. Same architectural choice as the AI provider registry:
explicit registration over auto-discovery, so reviewers can answer
"what tasks does this process know how to run?" by reading one short
function in `app/dependencies/orchestration.py`.
"""

from __future__ import annotations

from app.orchestration.exceptions import TaskNotRegisteredError
from app.orchestration.tasks.base import BaseTask


class _TaskAlreadyRegisteredError(Exception):
    """Raised at startup if two tasks claim the same registry name."""


class TaskRegistry:
    """Process-wide, name-keyed map of tasks.

    Constructed once during dependency wiring and treated as read-only
    afterwards. Mutation from request handlers is a bug.
    """

    __slots__ = ("_tasks",)

    def __init__(self) -> None:
        self._tasks: dict[str, BaseTask] = {}

    def register(self, task: BaseTask) -> None:
        if not task.name:
            raise ValueError(f"task {type(task).__name__} has no `name`")
        if task.name in self._tasks:
            raise _TaskAlreadyRegisteredError(task.name)
        self._tasks[task.name] = task

    def resolve(self, name: str) -> BaseTask:
        try:
            return self._tasks[name]
        except KeyError as exc:
            raise TaskNotRegisteredError(name) from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tasks.keys()))

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tasks

    def __len__(self) -> int:
        return len(self._tasks)


__all__ = ["TaskRegistry"]
