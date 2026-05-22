"""QA substrate exception hierarchy."""

from __future__ import annotations


class QAError(Exception):
    """Base class for QA substrate failures."""


class QAEvaluationError(QAError):
    """Raised when QA scoring cannot be produced from persisted evidence."""


class QAPersistenceError(QAError):
    """Raised by QA persistence implementations."""


__all__ = [
    "QAError",
    "QAEvaluationError",
    "QAPersistenceError",
]
