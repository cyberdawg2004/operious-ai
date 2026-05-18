"""Identity Primitives — Constitutional Vocabulary for Authority.

This module defines the typed identity primitives that anchor every
authority-bearing operation in Operious AI. They are the foundation
of Phase 1 (Enterprise Identity & Authority Infrastructure).

Constitutional role
-------------------
These primitives are the SINGLE SOURCE OF TRUTH for identity
vocabulary across the substrate. Every governance subject, session
trace, hardening audit, arbitration event, and coordination message
that carries an authority anchor MUST eventually use these types.

Authority root
--------------
The canonical authority anchor is the tuple
``(environment_id, tenant_id, principal_id)``. ``environment_id`` is
a PEER of ``tenant_id``, not a deployment-time-only concern. This
decision was ratified during Phase 1 wedge selection: cross-
environment authority MUST be forbidden at the substrate layer.

Design principles
-----------------
1. Runtime-transparent. Each primitive is a ``NewType`` over ``str``,
   so existing ``str`` call sites continue to work unchanged. This
   wedge introduces vocabulary WITHOUT behavioral change.
2. Leaf substrate. ``app.identity`` imports only from stdlib. No
   sibling substrate may be imported here. The leaf invariant is
   enforced by ``tests/test_identity_primitives.py``.
3. Total coercion. Each primitive ships a ``coerce_*`` helper that
   normalises raw input to the typed form or raises ``IdentityError``.
   Coercers strip surrounding whitespace and reject empty / whitespace-
   only / non-string inputs.
4. Replay-safe. ``NewType`` is erased at runtime, so adopting these
   primitives in serialisers does not perturb byte-level replay.

Out of scope (future Phase 1 wedges)
-----------------------------------
- Identity lineage / org hierarchy graph
- Tenant isolation policy
- RBAC capability subject
- Environment segmentation enforcement
- Session authority propagation

Those wedges build on top of these primitives but are NOT covered by
this module.
"""

from __future__ import annotations

from typing import NewType

TenantId = NewType("TenantId", str)
PrincipalId = NewType("PrincipalId", str)
OrganizationId = NewType("OrganizationId", str)
EnvironmentId = NewType("EnvironmentId", str)


class IdentityError(ValueError):
    """Raised when an identity primitive cannot be constructed from input."""


def _coerce(raw: object, kind: str) -> str:
    if not isinstance(raw, str):
        raise IdentityError(
            f"{kind} must be a string, got {type(raw).__name__}"
        )
    stripped = raw.strip()
    if not stripped:
        raise IdentityError(f"{kind} must be a non-empty string")
    return stripped


def coerce_tenant_id(raw: object) -> TenantId:
    """Normalise ``raw`` into a :class:`TenantId` or raise ``IdentityError``."""
    return TenantId(_coerce(raw, "tenant_id"))


def coerce_principal_id(raw: object) -> PrincipalId:
    """Normalise ``raw`` into a :class:`PrincipalId` or raise ``IdentityError``."""
    return PrincipalId(_coerce(raw, "principal_id"))


def coerce_organization_id(raw: object) -> OrganizationId:
    """Normalise ``raw`` into an :class:`OrganizationId` or raise ``IdentityError``."""
    return OrganizationId(_coerce(raw, "organization_id"))


def coerce_environment_id(raw: object) -> EnvironmentId:
    """Normalise ``raw`` into an :class:`EnvironmentId` or raise ``IdentityError``."""
    return EnvironmentId(_coerce(raw, "environment_id"))


__all__ = [
    "EnvironmentId",
    "IdentityError",
    "OrganizationId",
    "PrincipalId",
    "TenantId",
    "coerce_environment_id",
    "coerce_organization_id",
    "coerce_principal_id",
    "coerce_tenant_id",
]
