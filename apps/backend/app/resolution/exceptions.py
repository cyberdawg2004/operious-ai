"""Resolution substrate exceptions."""

from __future__ import annotations


class ResolutionError(RuntimeError):
    """Base class for resolution proposal failures."""


class ResolutionPersistenceError(ResolutionError):
    """Raised when resolution proposal persistence fails."""


class ResolutionValidationError(ResolutionError):
    """Raised when a proposal cannot be safely constructed."""


__all__ = [
    "ResolutionError",
    "ResolutionPersistenceError",
    "ResolutionValidationError",
]
