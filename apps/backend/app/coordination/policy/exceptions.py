"""Coordination policy exception hierarchy.

Mirrors the discipline of `app/coordination/exceptions.py`:

* `CoordinationPolicyError`              — base type.
* `CoordinationPolicyConfigurationError` — registry / chain / rule
                                            misconfiguration surfaced
                                            at composition time.
* `CoordinationPolicyEvaluationError`    — evaluator framework
                                            failure (an evaluator
                                            raised, a request was
                                            malformed). The runtime
                                            catches and folds these
                                            onto the evaluation
                                            envelope; the public API
                                            never re-raises.
* `CoordinationPolicyDeniedError`        — policy returned a blocking
                                            verdict (DENY / ESCALATE).
                                            NOT a runtime failure —
                                            the substrate behaved
                                            correctly; the verdict
                                            is the verdict. Used as
                                            an internal discriminator
                                            so the coordination
                                            runtime can branch on
                                            blocking vs non-blocking
                                            outcomes before
                                            governance runs.
* `CoordinationPolicyPersistenceError`   — persistence backend
                                            rejected / failed a
                                            write or read.

Architectural note: `CoordinationPolicyRuntime.evaluate()` itself
NEVER raises. The exception classes are the *internal* discriminators
that let the runtime decide how to populate the envelope.
"""

from __future__ import annotations


class CoordinationPolicyError(Exception):
    """Base class for coordination-policy substrate failures."""


class CoordinationPolicyConfigurationError(CoordinationPolicyError):
    """Registry / chain / rule composition error.

    Raised at composition time (registry registration, chain
    construction). Surfacing these as a distinct subclass keeps
    "fail fast at startup" semantics separate from runtime-evaluation
    error handling.
    """


class CoordinationPolicyEvaluationError(CoordinationPolicyError):
    """Evaluator framework rejected the request or an evaluator raised.

    Surfaced on the policy envelope as a failed evaluation; the
    coordination runtime translates it into a ``POLICY_ERROR``
    dispatch outcome.
    """


class CoordinationPolicyDeniedError(CoordinationPolicyError):
    """Policy returned a blocking verdict (DENY or ESCALATE).

    NOT a substrate failure — the substrate behaved correctly. This
    is the internal channel through which the coordination runtime
    differentiates blocking from non-blocking policy outcomes.
    """


class CoordinationPolicyPersistenceError(CoordinationPolicyError):
    """Persistence-layer failure (write-once violation, backend I/O)."""


__all__ = [
    "CoordinationPolicyError",
    "CoordinationPolicyConfigurationError",
    "CoordinationPolicyEvaluationError",
    "CoordinationPolicyDeniedError",
    "CoordinationPolicyPersistenceError",
]
