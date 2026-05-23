"""Typed governance exceptions.

Four shapes, each carrying enough structured metadata that supervisor
runtimes can reconstruct *why* the failure occurred without parsing
strings.

* `GovernanceViolationError`    — surfaced by guardrails when a DENY
                                  decision must abort execution. Carries
                                  the full decision so callers can audit.
* `PolicyEvaluationError`       — a policy raised during `evaluate()`.
                                  Wraps the original error and pins the
                                  policy + rule id (if known).
* `EnforcementExecutionError`   — a handler raised while applying a
                                  decision. Pins the handler + the
                                  decision being enforced.
* `GovernanceConfigurationError` — the runtime was assembled with an
                                  invalid configuration (unknown policy,
                                  missing handler, etc.). Fail-fast at
                                  boot, never at request time.

These exceptions are the **only** thing the substrate raises directly.
Normal "rule failed" outcomes flow through `GovernanceDecision`, not
exceptions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:  # Avoid import cycles — these types are referenced
    # in error metadata only.
    from app.governance.decisions import GovernanceDecision


class GovernanceError(Exception):
    """Base of every typed governance exception."""

    def __init__(
        self,
        message: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.metadata: Mapping[str, Any] = dict(metadata or {})


class GovernanceViolationError(GovernanceError):
    """Raised by guardrails when a DENY decision must abort execution.

    The decision is attached so callers can read the full lineage —
    which rules fired, with what severity, under which policy chain.
    """

    def __init__(
        self,
        message: str,
        *,
        decision: "GovernanceDecision",
    ) -> None:
        super().__init__(message, metadata={"decision_id": str(decision.decision_id)})
        self.decision = decision


class PolicyEvaluationError(GovernanceError):
    """A policy raised during `evaluate()`.

    Wraps the original error. The engine catches this, folds it into
    the trace, and the chain produces a synthetic DENY result tagged
    with `evaluation_error` metadata — fail-safe by default.
    """

    def __init__(
        self,
        message: str,
        *,
        policy_name: str,
        rule_id: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(
            message,
            metadata={"policy_name": policy_name, "rule_id": rule_id},
        )
        self.policy_name = policy_name
        self.rule_id = rule_id
        self.__cause__ = cause


class EnforcementExecutionError(GovernanceError):
    """A handler raised while applying a governance decision.

    Distinct from `PolicyEvaluationError`: this is about the *action*
    failing, not the verdict. The runtime catches this and folds it
    into the envelope as a failed enforcement; the original decision
    is preserved for audit.
    """

    def __init__(
        self,
        message: str,
        *,
        handler_name: str,
        decision: "GovernanceDecision",
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(
            message,
            metadata={
                "handler_name": handler_name,
                "decision_id": str(decision.decision_id),
            },
        )
        self.handler_name = handler_name
        self.decision = decision
        self.__cause__ = cause


class GovernanceConfigurationError(GovernanceError):
    """The runtime was assembled with an invalid configuration.

    Raised at DI / composition time, NEVER at request time. Examples:
    unknown policy name in a chain, missing handler for a decision
    kind, evaluation engine constructed without an aggregation rule.
    """


__all__ = [
    "GovernanceError",
    "GovernanceViolationError",
    "PolicyEvaluationError",
    "EnforcementExecutionError",
    "GovernanceConfigurationError",
]
