"""Enforcement handlers.

One handler per `Decision` value:

* `AllowHandler`             — no-op; records NO_OP outcome.
* `DenyHandler`              — records APPLIED with detail; the
                               guardrail layer is what *actually*
                               raises `GovernanceViolationError`.
* `RedactHandler`            — records APPLIED with the restrictions
                               that downstream guardrails must apply.
* `DegradeHandler`           — same as REDACT: records APPLIED + carries
                               restrictions; the assembly / AI
                               runtime layer enforces them.
* `EscalateHandler`          — records APPLIED with DEFERRED outcome
                               (the canonical "operator must act").
* `RequireApprovalHandler`   — records APPLIED with DEFERRED outcome.

Handlers do NOT mutate state. They produce frozen `EnforcementAction`
records that the runtime puts on the envelope. The *runtime*, in turn,
hands those actions to whatever calling code asked for governance —
and *that* code (or its guardrails) actually applies the action to
its own state.

This separation is on purpose:

* policies emit *verdicts*,
* handlers translate verdicts into structured *actions*,
* guardrails apply *actions* to live operational state.

Three layers. Each one is replaceable independently.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import ClassVar, Iterator

from app.governance.decisions import GovernanceDecision
from app.governance.enforcement.models import (
    EnforcementAction,
    EnforcementOutcome,
)
from app.governance.enums import Decision
from app.governance.exceptions import GovernanceConfigurationError

_ACTION_NAMESPACE = uuid.UUID("4d2c10a2-6c00-4f7c-8b3a-1f8d0c7e0003")


class BaseEnforcementHandler(ABC):
    """Contract every enforcement handler honours."""

    decision: ClassVar[Decision]
    name: ClassVar[str] = ""

    @abstractmethod
    async def apply(self, decision: GovernanceDecision) -> EnforcementAction:
        """Translate a decision into a durable enforcement action."""


# ─── Concrete handlers (one per decision class) ──────────────────────


class AllowHandler(BaseEnforcementHandler):
    decision = Decision.ALLOW
    name = "allow"

    async def apply(self, decision: GovernanceDecision) -> EnforcementAction:
        return EnforcementAction(
            action_id=_action_id(decision, self.name),
            handler_name=self.name,
            decision_id=decision.decision_id,
            outcome=EnforcementOutcome.NO_OP,
            detail="execution permitted",
        )


class DenyHandler(BaseEnforcementHandler):
    decision = Decision.DENY
    name = "deny"

    async def apply(self, decision: GovernanceDecision) -> EnforcementAction:
        return EnforcementAction(
            action_id=_action_id(decision, self.name),
            handler_name=self.name,
            decision_id=decision.decision_id,
            outcome=EnforcementOutcome.APPLIED,
            detail=decision.reason,
            metadata={
                "violation_count": len(decision.violations),
            },
        )


class RedactHandler(BaseEnforcementHandler):
    decision = Decision.REDACT
    name = "redact"

    async def apply(self, decision: GovernanceDecision) -> EnforcementAction:
        return EnforcementAction(
            action_id=_action_id(decision, self.name),
            handler_name=self.name,
            decision_id=decision.decision_id,
            outcome=EnforcementOutcome.APPLIED,
            detail=f"{len(decision.restrictions)} redaction restriction(s) emitted",
            metadata={
                "restriction_count": len(decision.restrictions),
            },
        )


class DegradeHandler(BaseEnforcementHandler):
    decision = Decision.DEGRADE
    name = "degrade"

    async def apply(self, decision: GovernanceDecision) -> EnforcementAction:
        return EnforcementAction(
            action_id=_action_id(decision, self.name),
            handler_name=self.name,
            decision_id=decision.decision_id,
            outcome=EnforcementOutcome.APPLIED,
            detail=f"{len(decision.restrictions)} degrade restriction(s) emitted",
            metadata={
                "restriction_count": len(decision.restrictions),
            },
        )


class EscalateHandler(BaseEnforcementHandler):
    decision = Decision.ESCALATE
    name = "escalate"

    async def apply(self, decision: GovernanceDecision) -> EnforcementAction:
        # Sprint I ships the escalation contract; the operator-side
        # queue lands in a later governance integration sprint. The
        # action is recorded as DEFERRED so supervisor runtimes know
        # the decision is awaiting out-of-band resolution.
        return EnforcementAction(
            action_id=_action_id(decision, self.name),
            handler_name=self.name,
            decision_id=decision.decision_id,
            outcome=EnforcementOutcome.DEFERRED,
            detail="escalation queued (out-of-band resolution required)",
        )


class RequireApprovalHandler(BaseEnforcementHandler):
    decision = Decision.REQUIRE_APPROVAL
    name = "require_approval"

    async def apply(self, decision: GovernanceDecision) -> EnforcementAction:
        return EnforcementAction(
            action_id=_action_id(decision, self.name),
            handler_name=self.name,
            decision_id=decision.decision_id,
            outcome=EnforcementOutcome.DEFERRED,
            detail="approval required before proceeding",
        )


# ─── Registry ────────────────────────────────────────────────────────


class EnforcementHandlerRegistry:
    """`Decision` → handler lookup, populated at composition time.

    Every `Decision` value MUST have a handler at composition time —
    the registry validates completeness once (`assert_complete`) so a
    missing handler is surfaced at boot, never at request time.
    """

    def __init__(self) -> None:
        self._handlers: dict[Decision, BaseEnforcementHandler] = {}

    def register(self, handler: BaseEnforcementHandler) -> None:
        if handler.decision in self._handlers:
            raise GovernanceConfigurationError(
                f"handler already registered for decision {handler.decision.value!r}"
            )
        self._handlers[handler.decision] = handler

    def get(self, decision: Decision) -> BaseEnforcementHandler:
        if decision not in self._handlers:
            raise GovernanceConfigurationError(
                f"no enforcement handler registered for decision {decision.value!r}"
            )
        return self._handlers[decision]

    def assert_complete(self) -> None:
        """Ensure every `Decision` value has a handler. Fail-fast."""
        missing = tuple(
            d.value for d in Decision if d not in self._handlers
        )
        if missing:
            raise GovernanceConfigurationError(
                f"enforcement handler registry is incomplete; "
                f"missing decisions: {missing}"
            )

    def __iter__(self) -> Iterator[BaseEnforcementHandler]:
        # Sorted by `Decision.value` so iteration is byte-stable across
        # processes and replays. Aggregation precedence is owned by
        # `Decision.precedence` — iteration order does NOT drive
        # most-restrictive-wins; it just needs to be deterministic.
        for decision in sorted(self._handlers.keys(), key=lambda d: d.value):
            yield self._handlers[decision]


def _action_id(decision: GovernanceDecision, handler_name: str) -> uuid.UUID:
    seed = f"{decision.decision_id}|{handler_name}|{decision.decision.value}"
    return uuid.uuid5(_ACTION_NAMESPACE, seed)


__all__ = [
    "BaseEnforcementHandler",
    "AllowHandler",
    "DenyHandler",
    "RedactHandler",
    "DegradeHandler",
    "EscalateHandler",
    "RequireApprovalHandler",
    "EnforcementHandlerRegistry",
]
