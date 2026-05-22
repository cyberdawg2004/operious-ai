"""Execution substrate wire vocabulary."""

from __future__ import annotations

from enum import StrEnum


class ExecutionKind(StrEnum):
    """Closed set of execution kinds currently admitted by the runtime."""

    DIAGNOSTIC_AGENT = "diagnostic_agent"


class ExecutionState(StrEnum):
    """Durable state of one execution authority record."""

    REQUESTED = "requested"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTERED = "dead_lettered"


class ExecutionAttemptState(StrEnum):
    """Durable state of one worker execution attempt."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTERED = "dead_lettered"


class ExecutionOutboxState(StrEnum):
    """Transport-publication state for one execution intent."""

    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


__all__ = [
    "ExecutionKind",
    "ExecutionAttemptState",
    "ExecutionOutboxState",
    "ExecutionState",
]
