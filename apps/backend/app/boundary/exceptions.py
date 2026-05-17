"""Boundary exception hierarchy.

* `BoundaryError`                  — base type.
* `BoundaryConfigurationError`     — registry / adapter composition
                                      error. Raised at composition
                                      time only.
* `BoundaryNormalizationError`     — adapter framework failure
                                      (adapter raised, payload
                                      malformed). Folded onto the
                                      envelope; the public API
                                      never re-raises.
* `BoundaryAuthenticationError`    — signature / token check
                                      failed at the adapter.
* `BoundaryReplayError`            — replay detector / idempotency
                                      registry rejected an input.
* `BoundaryPersistenceError`       — persistence backend rejected
                                      a write or read (e.g.
                                      write-once violation).

`BoundaryIngressRuntime.ingest()` and
`BoundaryEgressRuntime.emit()` NEVER raise. The exception classes
are the *internal* discriminators the runtime uses to decide how
to populate the envelope.
"""

from __future__ import annotations


class BoundaryError(Exception):
    """Base class for boundary substrate failures."""


class BoundaryConfigurationError(BoundaryError):
    """Composition-time error (duplicate adapter, missing config).

    Raised at construction time only — never at ingest/emit time.
    """


class BoundaryNormalizationError(BoundaryError):
    """Adapter framework rejected the payload or raised internally."""


class BoundaryAuthenticationError(BoundaryError):
    """Signature or token verification failed at the adapter."""


class BoundaryReplayError(BoundaryError):
    """Replay detector / idempotency registry rejected an input."""


class BoundaryPersistenceError(BoundaryError):
    """Persistence-layer failure (write-once violation, backend I/O)."""


__all__ = [
    "BoundaryError",
    "BoundaryConfigurationError",
    "BoundaryNormalizationError",
    "BoundaryAuthenticationError",
    "BoundaryReplayError",
    "BoundaryPersistenceError",
]
