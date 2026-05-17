"""Coordination exception hierarchy.

Mirrors the discipline of `app/governance/exceptions.py` and
`app/supervisor/exceptions.py`:

* `CoordinationError`              — base type; every coordination
                                     substrate failure is a subclass.
* `CoordinationValidationError`    — caller supplied a request that
                                     cannot be dispatched (missing
                                     recipient, unknown sender,
                                     malformed payload).
* `CoordinationGovernanceDeniedError`
                                   — governance produced a *blocking*
                                     decision. This is NOT a runtime
                                     failure (the substrate behaved
                                     correctly); it is the typed
                                     channel through which "denied"
                                     surfaces internally before the
                                     runtime folds it onto the
                                     dispatch result. The runtime
                                     catches and surfaces it through
                                     `CoordinationDispatchResult` — it
                                     is never re-raised to callers.
* `CoordinationPersistenceError`   — persistence backend rejected /
                                     failed a write or read.

Architectural note: `CoordinationRuntime.dispatch()` itself NEVER
raises — every failure mode lands on the `CoordinationDispatchResult`
the same way `GovernanceRuntime.evaluate()` lands every outcome on a
`GovernanceEnvelope`. The exception classes here are the *internal*
discriminators that let the runtime decide how to populate the
result.
"""

from __future__ import annotations


class CoordinationError(Exception):
    """Base class for coordination-substrate failures."""


class CoordinationValidationError(CoordinationError):
    """Request cannot be turned into a valid coordination envelope.

    Raised internally by the runtime's validation pass when:

    * sender / recipient identifiers are empty or unknown to the
      registry,
    * the message contradicts its declared direction,
    * timestamps / ordering fields are out of range,
    * the request supplies replay-override identifiers that
      contradict the supplied message.

    Surfaced on `CoordinationDispatchResult.outcome` as
    ``VALIDATION_ERROR``; the dispatch produces no persisted
    envelope when validation fails.
    """


class CoordinationGovernanceDeniedError(CoordinationError):
    """Governance returned a blocking decision.

    Distinct from `CoordinationValidationError` because the substrate
    DID accept the request and DID invoke governance — the denial is
    a correct governance verdict, not a substrate failure. This
    discipline matches `GovernanceRuntime`: a DENY is a *successful*
    governance evaluation that says "do not proceed".

    The runtime translates this into a `CoordinationDispatchResult`
    with outcome ``DENIED`` and a `CoordinationEnvelope` whose
    `status` is `CoordinationStatus.DENIED`. The envelope is
    persisted as an audit-grade record of the rejected attempt.
    """


class CoordinationPersistenceError(CoordinationError):
    """Persistence-layer failure (write-once violation, missing id,
    backend I/O failure).

    Surfaced on `CoordinationDispatchResult.outcome` as
    ``PERSISTENCE_ERROR``. The dispatch's governance evaluation may
    have succeeded, but the envelope could not be durably recorded;
    callers that require audit-grade durability MUST observe this
    outcome.
    """


__all__ = [
    "CoordinationError",
    "CoordinationValidationError",
    "CoordinationGovernanceDeniedError",
    "CoordinationPersistenceError",
]
