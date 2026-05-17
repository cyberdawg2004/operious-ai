"""Session exception hierarchy.

* `SessionError`                  — base type.
* `SessionConfigurationError`     — composition error (duplicate
                                     registration, missing dep).
* `SessionValidationError`        — caller passed a malformed
                                     contract.
* `SessionNotFoundError`          — read for an unknown session.
* `SessionLifecycleError`         — operation rejected by the
                                     current lifecycle phase
                                     (e.g. appending to TERMINATED).
* `SessionLineageError`           — lineage invariant violation
                                     (cycle detected, ancestor
                                     missing).
* `SessionPersistenceError`       — persistence backend rejected
                                     a write or read.
* `SessionReconstructionError`    — reconstruction-only failure
                                     mode (drift / corruption /
                                     missing record).

`SessionRuntime` public methods NEVER raise. The exception
classes are the *internal* discriminators the runtime uses to
populate the envelope.
"""

from __future__ import annotations


class SessionError(Exception):
    """Base class for session substrate failures."""


class SessionConfigurationError(SessionError):
    """Composition-time error.

    Raised at construction time only — never during a runtime call.
    """


class SessionValidationError(SessionError):
    """Caller-supplied request violates the substrate contract."""


class SessionNotFoundError(SessionError):
    """Read for an unknown session."""


class SessionLifecycleError(SessionError):
    """Operation rejected by the current lifecycle phase."""


class SessionLineageError(SessionError):
    """Lineage-invariant violation (cycle, missing ancestor)."""


class SessionPersistenceError(SessionError):
    """Persistence-layer failure (write-once violation, backend I/O)."""


class SessionReconstructionError(SessionError):
    """Reconstruction-only failure (drift / corruption / missing)."""


__all__ = [
    "SessionConfigurationError",
    "SessionError",
    "SessionLifecycleError",
    "SessionLineageError",
    "SessionNotFoundError",
    "SessionPersistenceError",
    "SessionReconstructionError",
    "SessionValidationError",
]
