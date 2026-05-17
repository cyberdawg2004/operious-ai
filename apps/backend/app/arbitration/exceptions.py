"""Operational arbitration exception hierarchy.

* `ArbitrationError`               — base type.
* `ArbitrationConfigurationError`  — registry / evaluator / case
                                      composition error. Raised at
                                      composition time only.
* `ArbitrationEvaluationError`     — evaluator framework failure
                                      (an evaluator raised, request
                                      was malformed). The runtime
                                      catches and folds these onto
                                      the envelope; the public API
                                      never re-raises.
* `ArbitrationPersistenceError`    — persistence backend rejected a
                                      write or read (e.g. write-once
                                      violation).

`OperationalArbitrationRuntime.evaluate()` NEVER raises. The
exception classes are the *internal* discriminators the runtime
uses to decide how to populate the envelope. Arbitration ALSO
never raises for semantic conflicts — a CONFLICT / DEADLOCK /
INCONCLUSIVE outcome is a correct interpretation, not a failure.
"""

from __future__ import annotations


class ArbitrationError(Exception):
    """Base class for arbitration substrate failures."""


class ArbitrationConfigurationError(ArbitrationError):
    """Composition-time error (duplicate evaluator, malformed case).

    Raised at construction time only — never at `evaluate()` time.
    """


class ArbitrationEvaluationError(ArbitrationError):
    """Evaluator framework rejected the request or an evaluator raised.

    Surfaced on the arbitration envelope as a failed evaluation; the
    runtime translates it into an `ARBITRATION_ERROR` outcome.
    """


class ArbitrationPersistenceError(ArbitrationError):
    """Persistence-layer failure (write-once violation, backend I/O)."""


__all__ = [
    "ArbitrationError",
    "ArbitrationConfigurationError",
    "ArbitrationEvaluationError",
    "ArbitrationPersistenceError",
]
