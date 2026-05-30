"""Shared capability legality adoption helpers.

The concrete governance runtime is supplied by the composition root.
This module stays import-safe for shared users by keeping governance
imports out of module initialization; the call path imports the
governance legality builder only when a gate is actually evaluated.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING

from app.identity.authority import AuthorityContext, AuthorityResolution
from app.identity.primitives import TenantId

if TYPE_CHECKING:
    from app.governance.capability.acts import OperationalAct
    from app.governance.enforcement.runtime import GovernanceRuntime
    from app.governance.envelopes import GovernanceEnvelope


class CapabilityDenied(Exception):
    """Capability legality gate denied an operational act."""

    __slots__ = ("act", "envelope")

    def __init__(
        self,
        *,
        act: OperationalAct,
        envelope: GovernanceEnvelope,
    ) -> None:
        self.act = act
        self.envelope = envelope
        if envelope.is_ok and envelope.decision is not None:
            reason = envelope.decision.reason or envelope.decision.decision.value
        elif envelope.error is not None:
            reason = (
                f"governance evaluation failed: "
                f"{envelope.error.__class__.__name__}"
            )
        else:
            reason = "no decision produced"
        super().__init__(
            f"capability legality denied for act {act.value!r}: {reason}"
        )


@dataclass(frozen=True, slots=True)
class CapabilityGateOutcome:
    """Capability-legality gate verdict and governance provenance."""

    denial: CapabilityDenied | None
    decision_id: uuid.UUID | None
    chain_id: str | None


async def evaluate_capability_gate(
    governance: GovernanceRuntime | None,
    *,
    act: OperationalAct,
    authority: AuthorityContext | None,
    resolution: AuthorityResolution,
    actor: str,
    resource: str = "",
    correlation_id: uuid.UUID | None = None,
) -> CapabilityGateOutcome:
    """Evaluate capability legality and return verdict plus provenance."""
    if governance is None:
        return CapabilityGateOutcome(
            denial=None,
            decision_id=None,
            chain_id=None,
        )
    gate_module = import_module("app.governance.capability.gate")
    capability_request = gate_module.CapabilityLegalityRequest
    evaluate_legality = gate_module.evaluate_capability_legality

    gate_authority = (
        authority
        if authority is not None
        else AuthorityContext(
            tenant_id=(
                TenantId(resolution.tenant_id)
                if resolution.tenant_id is not None
                else None
            )
        )
    )
    envelope = await evaluate_legality(
        governance,
        capability_request(
            authority=gate_authority,
            act=act,
            actor=actor,
            resource=resource,
            correlation_id=correlation_id,
        ),
    )
    decision_id, chain_id = _provenance_from_envelope(envelope)
    if not envelope.is_ok or envelope.decision is None:
        return CapabilityGateOutcome(
            denial=CapabilityDenied(act=act, envelope=envelope),
            decision_id=decision_id,
            chain_id=chain_id,
        )
    if not envelope.decision.is_allow:
        return CapabilityGateOutcome(
            denial=CapabilityDenied(act=act, envelope=envelope),
            decision_id=decision_id,
            chain_id=chain_id,
        )
    return CapabilityGateOutcome(
        denial=None,
        decision_id=decision_id,
        chain_id=chain_id,
    )


async def gate_or_deny(
    governance: GovernanceRuntime | None,
    *,
    act: OperationalAct,
    authority: AuthorityContext | None,
    resolution: AuthorityResolution,
    actor: str,
    resource: str = "",
    correlation_id: uuid.UUID | None = None,
) -> CapabilityDenied | None:
    """Return ``None`` for inert/ALLOW, otherwise a fail-closed denial."""
    outcome = await evaluate_capability_gate(
        governance,
        act=act,
        authority=authority,
        resolution=resolution,
        actor=actor,
        resource=resource,
        correlation_id=correlation_id,
    )
    return outcome.denial


def _provenance_from_envelope(
    envelope: GovernanceEnvelope,
) -> tuple[uuid.UUID | None, str | None]:
    decision = envelope.decision
    if decision is not None:
        return decision.decision_id, decision.policy_chain_id or None
    trace = envelope.trace
    return (
        trace.decision_id,
        trace.policy_chain_id or None,
    )


__all__ = [
    "CapabilityDenied",
    "CapabilityGateOutcome",
    "evaluate_capability_gate",
    "gate_or_deny",
]
