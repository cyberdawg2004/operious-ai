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

from app.governance.capability.acts import OperationalAct
from app.governance.capability.gate import (
    CapabilityLegalityRequest,
    evaluate_capability_legality,
)
from app.governance.enforcement.runtime import GovernanceRuntime
from app.governance.envelopes import GovernanceEnvelope
from app.identity.authority import AuthorityContext, AuthorityResolution


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

    Returns
    -------
    ``None``
        Gate is inert (``governance is None``) or the act is
        allowed (``envelope.is_ok and envelope.decision.is_allow``).
    :class:`CapabilityDenied`
        Gate is configured AND either the evaluation itself failed
        (fail-closed) or the verdict was not ALLOW. The caller MUST
        fold the returned exception into its fail-fast envelope
        without further branching.

    Construction rules
    ------------------
    * When the request carries a typed :class:`AuthorityContext`,
      that authority is consumed verbatim (capabilities ride with
      it).
    * Otherwise a synthetic ``AuthorityContext`` is built from
      ``resolution.tenant_id`` with **empty** capabilities. This is
      the constitutional fail-closed default for legacy ingress:
      callers that arrive without a verified authority context
      carry zero capabilities and therefore cannot legally perform
      capability-gated acts. The substrate refuses to invent
      capabilities the caller did not claim.
    """
    if governance is None:
        return None
    gate_authority = authority if authority is not None else AuthorityContext(
        tenant_id=resolution.tenant_id
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
    if not envelope.is_ok or envelope.decision is None:
        return CapabilityDenied(act=act, envelope=envelope)
    if not envelope.decision.is_allow:
        return CapabilityDenied(act=act, envelope=envelope)
    return None


__all__ = ["CapabilityDenied", "GovernanceRuntime", "gate_or_deny"]
