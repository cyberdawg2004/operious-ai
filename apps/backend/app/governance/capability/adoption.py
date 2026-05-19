"""Orchestration-runtime adoption helper for the capability gate (2.75-\u03b1).

The capability legality substrate (P2-B) shipped the **gate** —
``evaluate_capability_legality`` — but no orchestration runtime
consulted it. Effective RBAC was therefore fail-open: the gate
existed, no caller invoked it.

This module is the **single** call site every P2-A runtime adopts to
make the gate LIVE. A runtime adds an optional
``GovernanceRuntime`` dependency at construction time and invokes
:func:`gate_or_deny` exactly once at the top of each entry method,
immediately after :func:`request_authority_resolution`. On
``CapabilityDenied`` the runtime folds the exception into its
existing fail-fast envelope helper — no new failure path is
introduced.

Invariants
----------
* Inert when ``governance is None`` — preserves the pre-2.75-\u03b1
  test baseline. Production composition root MUST pin a
  ``GovernanceRuntime`` so the gate becomes a hard constraint.
* Fail-closed: evaluation failure (``not envelope.is_ok``) is
  treated as DENY. The substrate must never silently allow when
  the gate cannot produce a verdict.
* No per-runtime branching — every adopter follows the same
  three-line pattern. Per-runtime legality semantics would create
  the distributed-policy-chaos failure mode the substrate doctrine
  forbids.
* No bypass / override / dev-mode toggle.

Adoption pattern
----------------
::

    class FooRuntime:
        def __init__(self, *, governance: GovernanceRuntime | None = None, ...):
            self._capability_governance = governance
            ...

        async def entry(self, request: FooRequest) -> FooEnvelope:
            resolution = request_authority_resolution(request)
            denial = await gate_or_deny(
                self._capability_governance,
                act=OperationalAct.FOO_ENTRY,
                authority=request.authority,
                resolution=resolution,
                actor="foo_runtime",
            )
            if denial is not None:
                return self._failed_envelope(error=denial, ...)
            ...
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.governance.capability.acts import OperationalAct
from app.governance.capability.gate import (
    CapabilityLegalityRequest,
    evaluate_capability_legality,
)
from app.governance.enforcement.runtime import GovernanceRuntime
from app.governance.envelopes import GovernanceEnvelope
from app.identity.authority import AuthorityContext, AuthorityResolution
from app.identity.primitives import TenantId


class CapabilityDenied(Exception):
    """Capability legality gate denied an operational act.

    Carries the ``OperationalAct`` and the underlying
    :class:`GovernanceEnvelope` for forensic audit. Each adopting
    runtime catches this in its existing fail-fast helper without
    further inspection — the binary verdict is the contract.
    """

    __slots__ = ("act", "envelope")

    def __init__(
        self, *, act: OperationalAct, envelope: GovernanceEnvelope
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
    """Result of a capability-legality gate invocation.

    The outcome bundles the binary verdict
    (:attr:`denial` ``is None`` ⇔ ALLOW or inert) AND the governance
    provenance handles (Wedge 2.75-δ). Per-runtime adoption sites
    consume ``denial`` for fail-fast branching; runtimes that emit
    a :class:`GovernanceTrace`-compatible trace also project
    ``decision_id`` / ``chain_id`` to populate their existing
    ``governance_decision_id`` / ``governance_chain_id`` fields.

    Attributes:
        denial: ``None`` when the gate is inert (no ``GovernanceRuntime``)
            or the verdict is ALLOW; :class:`CapabilityDenied` otherwise.
        decision_id: UUID of the apex :class:`GovernanceDecision` that
            produced the verdict. ``None`` when the gate is inert or
            evaluation produced no decision.
        chain_id: Human-readable chain handle the decision came from.
            ``None`` when the gate is inert or no chain produced a
            verdict.
    """

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
    """Full capability-legality gate with governance provenance.

    Primitive used by :func:`gate_or_deny` and consumed directly by
    runtimes whose traces project ``governance_decision_id`` /
    ``governance_chain_id`` (Wedge 2.75-δ). Returns the full
    :class:`CapabilityGateOutcome` — denial verdict AND provenance.

    Construction rules — identical to :func:`gate_or_deny`. When the
    gate is inert (``governance is None``) the outcome carries
    ``decision_id is None`` / ``chain_id is None`` so callers always
    handle the inert case uniformly.
    """
    if governance is None:
        return CapabilityGateOutcome(
            denial=None, decision_id=None, chain_id=None
        )
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
    envelope = await evaluate_capability_legality(
        governance,
        CapabilityLegalityRequest(
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
        denial=None, decision_id=decision_id, chain_id=chain_id
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
    """Single-line capability-legality entry-point gate.

    Thin denial-only wrapper around :func:`evaluate_capability_gate`
    preserved for adoption sites that do not project governance
    provenance onto their traces. Returns:

    * ``None`` — gate inert OR verdict ALLOW; the caller proceeds.
    * :class:`CapabilityDenied` — verdict not ALLOW OR evaluation
      failed (fail-closed). The caller MUST fold the returned
      exception into its existing fail-fast envelope path without
      further branching.

    Runtimes that emit traces carrying
    ``governance_decision_id`` / ``governance_chain_id`` should call
    :func:`evaluate_capability_gate` directly instead so the
    provenance handles can be stamped onto the trace.
    """
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
    """Extract (decision_id, chain_id) from a governance envelope.

    The capability gate always produces a single-stage policy chain
    so the apex decision's ``decision_id`` is the authoritative
    handle. ``chain_id`` mirrors the chain that produced the apex
    verdict (joinable against the governance repository).
    """
    decision = envelope.decision
    if decision is not None:
        return decision.decision_id, decision.policy_chain_id or None
    trace = envelope.trace
    if trace is not None:
        return (
            trace.decision_id,
            trace.policy_chain_id or None,
        )
    return None, None


__all__ = [
    "CapabilityDenied",
    "CapabilityGateOutcome",
    "GovernanceRuntime",
    "evaluate_capability_gate",
    "gate_or_deny",
]
