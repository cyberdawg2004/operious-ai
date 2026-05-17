"""Vendor-neutral orchestration data shapes.

`TaskResult` and `WorkflowResult` are deliberately minimal — `output`
is a JSON-serialisable mapping (so persistence is trivial) and
`metadata` is opaque-but-traced (used for things like 'this AI call
took 3 attempts and 412ms').

Frozen dataclasses everywhere: results fan out to traces and
persistence rows, and accidental in-flight mutation is a class of bug
we want to make impossible by construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class TaskInput:
    """Input handed to one task invocation.

    `name` is the registry key the runtime resolves; `payload` is the
    JSON-serialisable input the task consumes.
    """

    name: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TaskResult:
    """Successful output of one task invocation.

    `output` is the JSON-serialisable result; `metadata` is opaque
    diagnostic data preserved on the task trace (attempt counts,
    upstream provider latency, etc.).
    """

    output: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    """Successful output of a workflow execution."""

    output: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["TaskInput", "TaskResult", "WorkflowResult"]
