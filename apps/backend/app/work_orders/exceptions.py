"""Work-order substrate exception hierarchy."""

from __future__ import annotations


class WorkOrderError(RuntimeError):
    """Base class for work-order substrate failures."""


class WorkOrderPersistenceError(WorkOrderError):
    """Persistence backend rejected or failed a work-order operation."""


class WorkOrderStateTransitionError(WorkOrderError):
    """A requested work-order state transition is not legal."""


__all__ = [
    "WorkOrderError",
    "WorkOrderPersistenceError",
    "WorkOrderStateTransitionError",
]
