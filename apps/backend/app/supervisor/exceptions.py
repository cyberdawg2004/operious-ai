"""Supervisor exception hierarchy.

Mirrors the discipline of `app/governance/exceptions.py`. Every
substrate failure mode is a typed subclass of `SupervisorError`. The
`SupervisorRuntime` itself catches everything and surfaces it on the
envelope; these exceptions are for *internal* surface clarity (e.g.
registry lookups, request validation).
"""

from __future__ import annotations


class SupervisorError(Exception):
    """Base class for supervisor-runtime failures."""


class EvaluatorConfigurationError(SupervisorError):
    """Evaluator registration / lookup failure."""


class InspectionRequestError(SupervisorError):
    """Caller supplied an inspection request that cannot be normalised
    into an `InspectionView` (e.g. neither live envelope nor replay
    records provided)."""


class SupervisorPersistenceError(SupervisorError):
    """Persistence-layer failure (write-once violation, missing id)."""


__all__ = [
    "SupervisorError",
    "EvaluatorConfigurationError",
    "InspectionRequestError",
    "SupervisorPersistenceError",
]
