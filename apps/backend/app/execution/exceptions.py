"""Execution substrate exception hierarchy."""

from __future__ import annotations


class ExecutionError(RuntimeError):
    """Base class for execution-substrate failures."""


class ExecutionPersistenceError(ExecutionError):
    """Persistence backend rejected or failed an execution operation."""


class ExecutionStateError(ExecutionError):
    """Execution state transition was not constitutionally valid."""


class ExecutionNotClaimableError(ExecutionStateError):
    """Execution cannot be claimed by the current worker attempt."""


__all__ = [
    "ExecutionError",
    "ExecutionNotClaimableError",
    "ExecutionPersistenceError",
    "ExecutionStateError",
]
