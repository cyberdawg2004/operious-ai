"""Hardening-substrate exception hierarchy.

Public runtime methods NEVER raise. The classes below are
internal discriminators that the runtime uses to populate
envelope errors.

The discipline: any attempt by hardening infrastructure to
**mutate** runtime behaviour raises `HardeningContainmentError`.
This is the central invariant of the hardening substrate.
"""

from __future__ import annotations


class HardeningError(Exception):
    """Base class for hardening-substrate failures."""


class HardeningConfigurationError(HardeningError):
    """Composition-time error (registry / dependency wiring)."""


class HardeningValidationError(HardeningError):
    """Caller-supplied request violates the substrate contract."""


class HardeningNotFoundError(HardeningError):
    """Read for an unknown hardening artifact."""


class HardeningContainmentError(HardeningError):
    """Hardening operation would leave its observational scope.

    Raised when:

    * A caller tries to make hardening trigger an automatic fix.
    * A validator attempts to mutate substrate state.
    * A failure-recording call is asked to invoke recovery.

    This exception is the central invariant of the hardening
    substrate.
    """


class HardeningPersistenceError(HardeningError):
    """Persistence backend rejected a write or read."""


class HardeningInvariantError(HardeningError):
    """A pinned invariant has drifted (used by validators)."""


__all__ = [
    "HardeningConfigurationError",
    "HardeningContainmentError",
    "HardeningError",
    "HardeningInvariantError",
    "HardeningNotFoundError",
    "HardeningPersistenceError",
    "HardeningValidationError",
]
