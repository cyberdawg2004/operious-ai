"""Escalation substrate exception surface."""

from __future__ import annotations


class EscalationError(RuntimeError):
    """Base escalation substrate error."""


class EscalationNotFoundError(EscalationError):
    """Raised when an escalation record is absent or tenant-invisible."""


class EscalationPersistenceError(EscalationError):
    """Raised when escalation persistence rejects an operation."""


class EscalationRuntimeError(EscalationError):
    """Raised when escalation runtime lineage is invalid."""


class EscalationResolutionError(EscalationError):
    """Raised when a manager resolution is not legal."""


__all__ = [
    "EscalationError",
    "EscalationNotFoundError",
    "EscalationPersistenceError",
    "EscalationResolutionError",
    "EscalationRuntimeError",
]
