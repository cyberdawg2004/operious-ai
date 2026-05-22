"""SOP intelligence substrate exceptions."""

from __future__ import annotations


class SOPIntelligenceError(RuntimeError):
    """Base class for SOP intelligence failures."""


class SOPIntelligenceNotFoundError(SOPIntelligenceError):
    """Raised when a required persisted evidence record is absent."""


class SOPIntelligenceEligibilityError(SOPIntelligenceError):
    """Raised when a session is not eligible for SOP proposal."""


class SOPIntelligencePersistenceError(SOPIntelligenceError):
    """Raised when approval proposal persistence fails."""


__all__ = [
    "SOPIntelligenceEligibilityError",
    "SOPIntelligenceError",
    "SOPIntelligenceNotFoundError",
    "SOPIntelligencePersistenceError",
]
