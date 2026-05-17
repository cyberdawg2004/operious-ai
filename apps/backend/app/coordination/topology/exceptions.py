"""Coordination topology exception hierarchy.

Mirrors `app/coordination/policy/exceptions.py` discipline:

* `CoordinationTopologyError`              — base type.
* `CoordinationTopologyConfigurationError` — declared topology /
                                              evaluator registry
                                              composition error
                                              (duplicate node ids,
                                              edges referring to
                                              unknown nodes, …).
                                              Raised at composition
                                              time only.
* `CoordinationTopologyEvaluationError`    — evaluator framework
                                              failure (an evaluator
                                              raised, a request was
                                              malformed). The
                                              runtime catches and
                                              folds these onto the
                                              evaluation envelope;
                                              the public API never
                                              re-raises.
* `CoordinationTopologyDeniedError`        — topology returned a
                                              blocking verdict.
                                              NOT a substrate
                                              failure — the
                                              substrate behaved
                                              correctly; the verdict
                                              is the verdict. Used
                                              as an internal
                                              discriminator so the
                                              coordination runtime
                                              can branch on blocking
                                              vs non-blocking
                                              outcomes before
                                              policy runs.
* `CoordinationTopologyPersistenceError`   — persistence backend
                                              rejected / failed a
                                              write or read.

Architectural note: `CoordinationTopologyRuntime.evaluate()` NEVER
raises. The exception classes are the *internal* discriminators
that let the runtime decide how to populate the envelope.
"""

from __future__ import annotations


class CoordinationTopologyError(Exception):
    """Base class for coordination-topology substrate failures."""


class CoordinationTopologyConfigurationError(CoordinationTopologyError):
    """Topology declaration / registry composition error.

    Raised at composition time (topology construction, registry
    registration, evaluator construction). Surfacing these as a
    distinct subclass keeps "fail fast at startup" semantics
    separate from runtime-evaluation error handling.
    """


class CoordinationTopologyEvaluationError(CoordinationTopologyError):
    """Evaluator framework rejected the request or an evaluator raised.

    Surfaced on the topology envelope as a failed evaluation; the
    coordination runtime translates it into a ``TOPOLOGY_ERROR``
    dispatch outcome.
    """


class CoordinationTopologyDeniedError(CoordinationTopologyError):
    """Topology returned a blocking verdict.

    NOT a substrate failure — the substrate behaved correctly. This
    is the internal channel through which the coordination runtime
    differentiates blocking from non-blocking topology outcomes.
    """


class CoordinationTopologyPersistenceError(CoordinationTopologyError):
    """Persistence-layer failure (write-once violation, backend I/O)."""


__all__ = [
    "CoordinationTopologyError",
    "CoordinationTopologyConfigurationError",
    "CoordinationTopologyEvaluationError",
    "CoordinationTopologyDeniedError",
    "CoordinationTopologyPersistenceError",
]
