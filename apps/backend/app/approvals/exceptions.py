"""Case approval errors."""

from __future__ import annotations


class CaseApprovalError(RuntimeError):
    """Base exception for the approval queue substrate."""


class CaseApprovalPersistenceError(CaseApprovalError):
    """Raised when durable approval state cannot be persisted."""


class CaseApprovalNotFoundError(CaseApprovalError):
    """Raised when a case is absent or tenant-invisible."""


class CaseApprovalLifecycleError(CaseApprovalError):
    """Raised when a transition is not allowed."""


class CaseApprovalGuidanceRejectedError(CaseApprovalError):
    """Raised when operator guidance fails injection controls."""


class CaseApprovalRuntimeError(CaseApprovalError):
    """Raised when approval execution cannot complete."""


__all__ = [
    "CaseApprovalError",
    "CaseApprovalGuidanceRejectedError",
    "CaseApprovalLifecycleError",
    "CaseApprovalNotFoundError",
    "CaseApprovalPersistenceError",
    "CaseApprovalRuntimeError",
]
