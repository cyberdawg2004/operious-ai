"""`CoordinationDispatchResult` — apex output of `dispatch()`.

Pairs with `CoordinationTrace` (which is the lineage record) and
optionally a `CoordinationEnvelope` (which is the persisted
artifact). The runtime returns exactly one result per dispatch call
and never raises.

Outcome semantics — pinned wire-format vocabulary:

* `ACCEPTED`           — governance allowed; envelope persisted with
                         status `DISPATCHED`.
* `DEGRADED`           — governance returned DEGRADE / REDACT;
                         envelope persisted with status `DEGRADED`
                         and restrictions surfaced through the
                         governance decision.
* `DENIED`             — governance returned DENY / REQUIRE_APPROVAL
                         / ESCALATE; envelope persisted with status
                         `DENIED` as an audit-grade record. This is
                         NOT a runtime failure (preserve governance
                         semantic discipline).
* `POLICY_DENIED`      — coordination-policy (topology
                         authorisation) returned DENY before
                         governance ran. Envelope persisted with
                         status `POLICY_DENIED`. **Distinct
                         semantic** from `DENIED` — Sprint L2 Rule 2.
* `POLICY_ESCALATED`   — coordination-policy returned ESCALATE.
                         Dispatch is blocked pending escalation;
                         envelope persisted with status
                         `POLICY_DENIED` (escalation is treated as a
                         blocking topology verdict, but the trace +
                         policy envelope record the escalation
                         requirement separately).
* `POLICY_ERROR`       — the coordination-policy substrate itself
                         failed (an evaluator raised, request was
                         malformed). The coordination envelope is
                         persisted with status `FAILED` to keep the
                         audit trail.
* `TOPOLOGY_DENIED`    — coordination *topology* (structural
                         authority — declared edges, paths) returned
                         DENIED before policy / governance ran.
                         Envelope persisted with status
                         `TOPOLOGY_DENIED`. **Distinct semantic** —
                         Sprint L3 final directive.
* `TOPOLOGY_ESCALATED` — coordination topology returned ESCALATED:
                         the dispatch traverses a declared escalation
                         edge. Dispatch is blocked at the topology
                         layer; envelope persisted with status
                         `TOPOLOGY_DENIED`. Distinct from
                         `POLICY_ESCALATED` (which is a policy-rule
                         escalation), and distinct from `DENIED`
                         (governance refusal).
* `TOPOLOGY_DEPTH_EXCEEDED`
                       — coordination topology returned
                         DEPTH_EXCEEDED: recursive-delegation
                         protection tripped. Envelope persisted with
                         status `TOPOLOGY_DENIED`.
* `TOPOLOGY_BOUNDARY_VIOLATION`
                       — coordination topology returned
                         BOUNDARY_VIOLATION: dispatch crossed an
                         unauthorised authority boundary. Envelope
                         persisted with status `TOPOLOGY_DENIED`.
* `TOPOLOGY_ERROR`     — the coordination-topology substrate itself
                         failed (an evaluator raised, registry was
                         empty). Envelope persisted with status
                         `FAILED`.
* `VALIDATION_ERROR`   — request rejected before topology / policy /
                         governance ran (bad sender / recipient,
                         malformed message). No envelope is persisted.
* `PERSISTENCE_ERROR`  — policy + governance succeeded but the
                         persistence backend rejected the write. The
                         envelope MAY have been partially written;
                         callers MUST observe this outcome and treat
                         the dispatch as not-durably-recorded.
* `GOVERNANCE_ERROR`   — `GovernanceRuntime.evaluate()` returned a
                         failed envelope (engine / config error).
                         The coordination envelope is persisted with
                         status `FAILED` to keep the audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.coordination.envelopes import CoordinationEnvelope
from app.coordination.identity import CoordinationId
from app.coordination.tracing import CoordinationTrace


class CoordinationDispatchOutcome(StrEnum):
    """Terminal outcome of one `CoordinationRuntime.dispatch()` call."""

    ACCEPTED = "accepted"
    DEGRADED = "degraded"
    DENIED = "denied"
    POLICY_DENIED = "policy_denied"
    POLICY_ESCALATED = "policy_escalated"
    POLICY_ERROR = "policy_error"
    TOPOLOGY_DENIED = "topology_denied"
    TOPOLOGY_ESCALATED = "topology_escalated"
    TOPOLOGY_DEPTH_EXCEEDED = "topology_depth_exceeded"
    TOPOLOGY_BOUNDARY_VIOLATION = "topology_boundary_violation"
    TOPOLOGY_ERROR = "topology_error"
    VALIDATION_ERROR = "validation_error"
    PERSISTENCE_ERROR = "persistence_error"
    GOVERNANCE_ERROR = "governance_error"


@dataclass(frozen=True, slots=True)
class CoordinationDispatchResult:
    """Apex output of one `CoordinationRuntime.dispatch()` call.

    The runtime always returns a result — it NEVER raises. Consumers
    branch on `outcome` (or the `is_ok` / `is_denied` /
    `is_validation_error` helpers).

    Attributes:
        coordination_id:  Identifier of THIS dispatch.
        outcome:           Terminal outcome.
        envelope:          The persisted envelope, when one was built.
                           ``None`` for outcomes that fail before the
                           envelope can be constructed
                           (`VALIDATION_ERROR`).
        trace:             The lineage trace for this dispatch. Always
                           present.
        error:             Short human-readable error description for
                           non-ACCEPTED outcomes. ``None`` for ACCEPTED
                           and DEGRADED.
        metadata:          Free-form, mirrors the request metadata
                           plus substrate-added fields.
    """

    coordination_id: CoordinationId
    outcome: CoordinationDispatchOutcome
    trace: CoordinationTrace
    envelope: CoordinationEnvelope | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    # ─── Branching helpers ────────────────────────────────────────────

    @property
    def is_ok(self) -> bool:
        """True iff the dispatch was successfully accepted / degraded.

        DENY is NOT `is_ok` — DENY is a *correct* governance verdict
        that says "do not proceed". Callers branching on "did the
        recipient effectively receive the message?" should check
        `is_ok`. Callers branching on "did the substrate behave
        correctly?" should check `is_substrate_ok`.
        """
        return self.outcome in {
            CoordinationDispatchOutcome.ACCEPTED,
            CoordinationDispatchOutcome.DEGRADED,
        }

    @property
    def is_denied(self) -> bool:
        """True iff governance denied. Distinct from `is_policy_denied`."""
        return self.outcome is CoordinationDispatchOutcome.DENIED

    @property
    def is_policy_denied(self) -> bool:
        """True iff coordination-policy denied. Distinct from `is_denied`."""
        return self.outcome is CoordinationDispatchOutcome.POLICY_DENIED

    @property
    def is_policy_escalated(self) -> bool:
        """True iff coordination-policy returned ESCALATE (blocking)."""
        return self.outcome is CoordinationDispatchOutcome.POLICY_ESCALATED

    @property
    def is_policy_error(self) -> bool:
        """True iff the coordination-policy substrate itself failed."""
        return self.outcome is CoordinationDispatchOutcome.POLICY_ERROR

    @property
    def is_policy_blocked(self) -> bool:
        """True iff blocked by coordination-policy (DENY or ESCALATE).

        Use this when callers want a single boolean across both
        blocking policy verdicts; the discrete properties remain the
        authority on semantic separation.
        """
        return self.outcome in {
            CoordinationDispatchOutcome.POLICY_DENIED,
            CoordinationDispatchOutcome.POLICY_ESCALATED,
        }

    @property
    def is_topology_denied(self) -> bool:
        """True iff coordination-topology returned DENIED."""
        return self.outcome is CoordinationDispatchOutcome.TOPOLOGY_DENIED

    @property
    def is_topology_escalated(self) -> bool:
        """True iff coordination-topology returned ESCALATED."""
        return (
            self.outcome
            is CoordinationDispatchOutcome.TOPOLOGY_ESCALATED
        )

    @property
    def is_topology_depth_exceeded(self) -> bool:
        """True iff coordination-topology returned DEPTH_EXCEEDED."""
        return (
            self.outcome
            is CoordinationDispatchOutcome.TOPOLOGY_DEPTH_EXCEEDED
        )

    @property
    def is_topology_boundary_violation(self) -> bool:
        """True iff coordination-topology returned BOUNDARY_VIOLATION."""
        return (
            self.outcome
            is CoordinationDispatchOutcome.TOPOLOGY_BOUNDARY_VIOLATION
        )

    @property
    def is_topology_error(self) -> bool:
        """True iff the coordination-topology substrate itself failed."""
        return self.outcome is CoordinationDispatchOutcome.TOPOLOGY_ERROR

    @property
    def is_topology_blocked(self) -> bool:
        """True iff blocked by coordination-topology.

        Single boolean across every topology verdict (DENIED,
        ESCALATED, DEPTH_EXCEEDED, BOUNDARY_VIOLATION). The discrete
        properties remain the authority on which structural failure
        mode occurred.
        """
        return self.outcome in {
            CoordinationDispatchOutcome.TOPOLOGY_DENIED,
            CoordinationDispatchOutcome.TOPOLOGY_ESCALATED,
            CoordinationDispatchOutcome.TOPOLOGY_DEPTH_EXCEEDED,
            CoordinationDispatchOutcome.TOPOLOGY_BOUNDARY_VIOLATION,
        }

    @property
    def is_validation_error(self) -> bool:
        return self.outcome is CoordinationDispatchOutcome.VALIDATION_ERROR

    @property
    def is_persistence_error(self) -> bool:
        return self.outcome is CoordinationDispatchOutcome.PERSISTENCE_ERROR

    @property
    def is_governance_error(self) -> bool:
        return self.outcome is CoordinationDispatchOutcome.GOVERNANCE_ERROR

    @property
    def is_substrate_ok(self) -> bool:
        """True iff the substrate itself behaved correctly.

        Every non-error outcome counts as substrate-OK — the runtime
        (and topology / policy / governance substrates) did their
        jobs; the verdicts are what they are. Only VALIDATION /
        PERSISTENCE / GOVERNANCE / POLICY / TOPOLOGY errors indicate
        the substrate could not complete a dispatch.
        """
        return self.outcome in {
            CoordinationDispatchOutcome.ACCEPTED,
            CoordinationDispatchOutcome.DEGRADED,
            CoordinationDispatchOutcome.DENIED,
            CoordinationDispatchOutcome.POLICY_DENIED,
            CoordinationDispatchOutcome.POLICY_ESCALATED,
            CoordinationDispatchOutcome.TOPOLOGY_DENIED,
            CoordinationDispatchOutcome.TOPOLOGY_ESCALATED,
            CoordinationDispatchOutcome.TOPOLOGY_DEPTH_EXCEEDED,
            CoordinationDispatchOutcome.TOPOLOGY_BOUNDARY_VIOLATION,
        }


__all__ = [
    "CoordinationDispatchOutcome",
    "CoordinationDispatchResult",
]
