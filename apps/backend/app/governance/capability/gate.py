"""Capability legality gate — singular evaluation surface (P2-B).

This is the ONLY legitimate construction site for a
:class:`CapabilityGovernanceSubject` used for legality. The gate is a
pure builder + a thin async invoker around
:class:`app.governance.GovernanceRuntime`.

Architectural invariants (enforced by tests under
``tests/test_capability_legality_gate.py``)
──────────────────────────────────────────
* The gate never inspects, mutates, or infers values from anything
  other than its declared :class:`CapabilityLegalityRequest` inputs.
* No orchestration code may import :class:`CapabilityGovernanceSubject`
  or :class:`RBACPolicy` directly — both are encapsulated behind the
  gate. Orchestration consumes only the resulting envelope.
* No branching on the operational act inside this module. The
  :class:`OperationalAct` enum is the input; the evaluation path is
  identical for every value. Per-act fast paths would create a
  parallel legality semantic.
* No bypass / override / dev-mode toggles. The fail-closed semantics
  of :class:`RBACPolicy` (DENY when required not in held, DENY when
  required is unspecified) are the only configured behaviour.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.governance.capability.acts import OperationalAct
from app.governance.context import GovernanceContext
from app.governance.enforcement.runtime import GovernanceRuntime
from app.governance.envelopes import GovernanceEnvelope
from app.governance.enums import EnforcementStage
from app.governance.subjects.capability import (
    CapabilityGovernanceSubject,
)
from app.identity.authority import AuthorityContext


@dataclass(frozen=True, slots=True)
class CapabilityLegalityRequest:
    """Closed input set the legality gate accepts.

    Attributes:
        authority: The verified authority context. Held capabilities
            are read directly from ``authority.capabilities``. The
            gate does not consult any other field for legality.
        act: The operational act being attempted. The enum value is
            both the canonical ``action`` on the
            :class:`GovernanceContext` and the
            ``required_capability`` on the
            :class:`CapabilityGovernanceSubject`.
        resource: Opaque resource identifier (free-form,
            substrate-specific). Empty string means "unspecified".
            The gate does NOT parse this; it is propagated onto the
            trace verbatim.
        actor: Free-form attribution of the caller. Defaults to
            ``"system"`` for consistency with
            :class:`GovernanceContext`.
        correlation_id: Optional higher-level correlation handle.
    """

    authority: AuthorityContext
    act: OperationalAct
    resource: str = ""
    actor: str = "system"
    correlation_id: uuid.UUID | None = None


def build_capability_context(
    request: CapabilityLegalityRequest,
) -> GovernanceContext:
    """Pure builder. Returns the GovernanceContext that a legality
    evaluation will consume.

    The function is deterministic and replay-safe: identical inputs
    produce structurally identical outputs. No defaults are derived
    from clocks, environment, or globals.
    """
    subject = CapabilityGovernanceSubject(
        required_capability=request.act.value,
        held_capabilities=request.authority.capabilities,
        tenant_id=request.authority.tenant_id,
        actor=request.actor,
    )
    return GovernanceContext(
        stage=EnforcementStage.PRE_REQUEST,
        action=request.act.value,
        resource=request.resource,
        actor=request.actor,
        tenant_id=request.authority.tenant_id,
        subject=subject,
        correlation_id=request.correlation_id,
    )


async def evaluate_capability_legality(
    governance: GovernanceRuntime,
    request: CapabilityLegalityRequest,
) -> GovernanceEnvelope:
    """Evaluate the legality of ``request.act`` for ``request.authority``.

    Returns the :class:`GovernanceEnvelope` produced by the
    governance runtime. Orchestration consumers MUST treat the
    decision as a binary verdict:

    * ``envelope.decision.decision == Decision.ALLOW`` → proceed
    * anything else (typically ``Decision.DENY``) → fold into a
      fail-fast envelope at the orchestration entry point. Do NOT
      branch on rule_id, do NOT branch on metadata, do NOT
      "downgrade" the verdict.
    """
    context = build_capability_context(request)
    return await governance.evaluate(context)


__all__ = [
    "CapabilityLegalityRequest",
    "build_capability_context",
    "evaluate_capability_legality",
]
