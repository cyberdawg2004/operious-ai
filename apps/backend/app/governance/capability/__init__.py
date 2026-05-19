"""Capability legality substrate (P2-B).

Constitutional positioning
──────────────────────────
This sub-package is the **singular** answer to the question:

    "Is this authority permitted to perform this operational act?"

It exports exactly two things — no more, no less:

* :class:`OperationalAct`         — the closed, namespaced catalog of
                                    operational acts that require
                                    capability legality.
* :func:`evaluate_capability_legality` /
  :func:`build_capability_context` — the only legitimate construction
                                    site for a
                                    :class:`CapabilityGovernanceSubject`
                                    used for legality (Branch B).

What this module DOES NOT do (aggressive prevention):

* It does NOT translate roles into capabilities. Roles, group
  memberships, and similar inputs are out of scope. Capabilities are
  what the authority context carries; the gate consumes that frozenset
  verbatim.
* It does NOT branch on the operational act. Every act is a single
  string compared against the held set by :class:`RBACPolicy`. No
  per-act fast paths, no per-act bypass.
* It does NOT short-circuit the governance runtime. Every legality
  evaluation flows through :class:`app.governance.GovernanceRuntime`
  so audit, replay, and metrics are uniform.
* It does NOT expose a "developer override", "admin bypass",
  "skip_rbac", or any other backdoor. There is one decision path.

Orchestration adoption (future wedge): orchestration runtimes call
:func:`evaluate_capability_legality` exactly once at the top of an
entry method, after :func:`request_authority_resolution`. On
``Decision.DENY`` they MUST fold the envelope into their own
fail-fast envelope without further branching.
"""

from app.governance.capability.acts import OperationalAct
from app.governance.capability.adoption import (
    CapabilityDenied,
    CapabilityGateOutcome,
    GovernanceRuntime,
    evaluate_capability_gate,
    gate_or_deny,
)
from app.governance.capability.gate import (
    CapabilityLegalityRequest,
    build_capability_context,
    evaluate_capability_legality,
)

__all__ = [
    "CapabilityDenied",
    "CapabilityGateOutcome",
    "CapabilityLegalityRequest",
    "GovernanceRuntime",
    "OperationalAct",
    "build_capability_context",
    "evaluate_capability_gate",
    "evaluate_capability_legality",
    "gate_or_deny",
]
