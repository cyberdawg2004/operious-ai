"""Execution scheduling primitives.

Sprint F's runtime is synchronous and deterministic — workflows drive
task sequencing in code by calling `runner.run_task(name, payload)`.
That's the right starting point: it is inspectable, auditable, and
makes execution flow trivial to reason about.

This module exists for the *next* layer of orchestration: data-driven
scheduling. A future scheduler (priority queue, delayed dispatch,
rate-limited dispatch) will consume `ScheduledTask` envelopes rather
than re-defining its own input shape.

Today the only emitter of `ScheduledTask` is hand-written workflow
code that prefers the data form; the runtime accepts both styles via
its task-runner interface. We deliberately do NOT ship a scheduler in
this sprint — it would commit us to a queue, durability, and ordering
semantics we have not yet earned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ScheduledTask:
    """A task selected for execution by a workflow.

    `name` is the task-registry key; `payload` is the JSON-serialisable
    input handed to the task. `metadata` is propagated into the task's
    trace.
    """

    name: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["ScheduledTask"]
