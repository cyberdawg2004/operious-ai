"""`AuthorityContext` — the typed authority tuple.

What this module establishes
----------------------------
The substrate's canonical value object for authority composition. An
``AuthorityContext`` bundles the four typed identity primitives
established by Wedge A (``TenantId``, ``PrincipalId``,
``OrganizationId``, ``EnvironmentId``) into a single immutable,
slot-allocated, frozen dataclass.

Constitutional role
-------------------
Authority — "WHO is requesting this operation, on behalf of WHICH
organizational unit, in WHICH environment?" — is currently expressed
across the substrate as a loose collection of ``str | None`` fields
scattered through dataclass surfaces (boundary contracts, runtime
envelopes, persistence records). The Wedge B1 audit
(``docs/identity/tenant-propagation-audit.md``) catalogued the
resulting drift: no centralised resolver, no consistency check
between siblings, and tenant authority effectively derived from
``BoundarySource`` inversion (BS-1).

This module introduces the SINGLE value object that future wedges
will require at every authority ingress site. The discipline:

* Authority is a TUPLE, not a bag of optional strings.
* Authority is FROZEN — once stamped at ingress, it never mutates.
* Authority is constructed through a validating gateway
  (``AuthorityContext.from_raw``) that runs every component through
  the wedge-A ``coerce_*`` helpers, so the only way to materialise
  an ``AuthorityContext`` carrying junk identifiers is to bypass
  the gateway entirely.

What this wedge does NOT do
---------------------------
* It does NOT yet require ``AuthorityContext`` at any ingress point.
  Boundary contracts get an OPTIONAL ``authority`` field that
  coexists with the legacy ``tenant_id: str | None`` for now.
* It does NOT touch HTTP middleware — request-level extraction is a
  separate wedge (deferred per Wedge B2 directive).
* It does NOT touch governance, runtime, persistence, or
  orchestration. ``AuthorityContext`` is not consumed by any runtime
  path in this commit. The wedge is purely about establishing the
  typed vocabulary at the boundary contract surface so the next
  wedges can adopt it.
* It does NOT implement RBAC. Authority composition is necessary
  for RBAC but is not RBAC itself.

Equality & hashing
------------------
``AuthorityContext`` is value-equal when every field matches. It is
hashable because every field is either ``None`` or a string-typed
``NewType`` (str-derived, immutable). This makes it usable as a
dictionary key for future authority-keyed caches without further
wrapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.identity.primitives import (
    EnvironmentId,
    OrganizationId,
    PrincipalId,
    TenantId,
    coerce_environment_id,
    coerce_organization_id,
    coerce_principal_id,
    coerce_tenant_id,
)


@dataclass(frozen=True, slots=True)
class AuthorityContext:
    """Typed authority tuple stamped at substrate ingress.

    Every field is OPTIONAL because not every ingress path carries a
    complete authority chain (anonymous webhook callbacks, internal
    runtime calls, replay reconstruction, etc.). When a field is
    present it carries the corresponding typed identity primitive
    — never a raw string. Construction through ``from_raw`` is the
    only validated path; direct ``AuthorityContext(...)`` bypasses
    coercion (intentional — replay reconstruction needs that escape
    hatch).

    Attributes:
        tenant_id:       The customer / organization-scope handle.
                         ``None`` denotes a constitutionally-tenantless
                         operation (e.g. health checks, anonymous
                         lineage). Distinct from ``TenantId("")``.
        principal_id:    The acting user / service identity.
        organization_id: The organizational unit within the tenant
                         (sub-tenant scope).
        environment_id:  The deployment environment
                         (production / staging / sandbox).
    """

    tenant_id: TenantId | None = None
    principal_id: PrincipalId | None = None
    organization_id: OrganizationId | None = None
    environment_id: EnvironmentId | None = None

    @classmethod
    def from_raw(
        cls,
        *,
        tenant_id: str | None = None,
        principal_id: str | None = None,
        organization_id: str | None = None,
        environment_id: str | None = None,
    ) -> "AuthorityContext":
        """Validate-and-construct gateway.

        Each non-``None`` component is run through its corresponding
        ``coerce_*`` helper, which strips whitespace and rejects
        non-string / empty / whitespace-only input by raising
        ``IdentityError``. Components left at ``None`` pass through
        without validation — that is the explicit
        "no-authority-for-this-axis" channel.

        This is the constitutional entry point for HTTP middleware,
        adapters, and any other ingress surface that produces an
        ``AuthorityContext`` from untyped strings.
        """
        return cls(
            tenant_id=(
                coerce_tenant_id(tenant_id)
                if tenant_id is not None
                else None
            ),
            principal_id=(
                coerce_principal_id(principal_id)
                if principal_id is not None
                else None
            ),
            organization_id=(
                coerce_organization_id(organization_id)
                if organization_id is not None
                else None
            ),
            environment_id=(
                coerce_environment_id(environment_id)
                if environment_id is not None
                else None
            ),
        )

    @property
    def is_tenantless(self) -> bool:
        """True when this authority carries no tenant scope.

        Useful for substrates that need to branch on the
        tenant-versus-tenantless authority distinction without
        unwrapping the field. Constitutionally distinct from
        ``tenant_id == ""`` — the latter is a rejected input that
        cannot exist on a validly-coerced ``AuthorityContext``.
        """
        return self.tenant_id is None

    @property
    def is_fully_anonymous(self) -> bool:
        """True when no axis of authority is supplied at all.

        Future ingress middleware will likely reject fully-anonymous
        ingress to authenticated endpoints. The property exists so
        that policy code can express the predicate without knowing
        which fields exist on the dataclass.
        """
        return (
            self.tenant_id is None
            and self.principal_id is None
            and self.organization_id is None
            and self.environment_id is None
        )


class AuthoritySource(StrEnum):
    """Constitutional taxonomy of which input produced an effective tenant_id.

    Wedge B6 introduces this enum so that every site that resolves a
    tenant authority records the SOURCE of that resolution. Replay
    reconstruction can then audit the attribution chain without
    re-running the resolution logic.

    Members:
      * ``TYPED_AUTHORITY``  — the ``AuthorityContext.tenant_id`` field
                                supplied at the typed-ingress surface
                                (Wedge B2). The constitutional source
                                going forward.
      * ``LEGACY_TENANT``    — the legacy ``request.tenant_id: str | None``
                                field. Permitted during the typed-
                                ingress transition; Wedge B2's
                                coexistence invariant guarantees it
                                agrees with ``TYPED_AUTHORITY`` when
                                both are supplied.
      * ``OBSERVED_TENANT``  — the tenant observed on the underlying
                                execution (e.g.,
                                ``AgentExecutionTrace.tenant_id`` from
                                Wedge B3). Used as a fallback when
                                neither typed nor legacy authority
                                was supplied at the call site.
      * ``NONE``             — every axis was absent. The operation
                                is constitutionally tenantless.
    """

    TYPED_AUTHORITY = "typed_authority"
    LEGACY_TENANT = "legacy_tenant"
    OBSERVED_TENANT = "observed_tenant"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class AuthorityResolution:
    """Result of resolving an effective tenant_id from multiple input axes.

    Pairs the resolved ``tenant_id`` with the ``AuthoritySource`` that
    produced it. Frozen, slotted, value-equal — usable as a dictionary
    key for future authority-keyed caches.

    Constitutional invariant: ``source == AuthoritySource.NONE`` IFF
    ``tenant_id is None``. The two carry the same information through
    different lenses (presence vs attribution).
    """

    tenant_id: str | None
    source: AuthoritySource


def resolve_authority(
    *,
    typed: AuthorityContext | None,
    legacy_tenant_id: str | None,
    observed_tenant_id: str | None,
) -> AuthorityResolution:
    """Singular, deterministic, traceable tenant authority resolution.

    Replaces the two-source ``request.tenant_id or view.tenant_id``
    coalescing pattern catalogued by audit defect DR-3 (Wedge B1).
    The resolution rules are pinned here as the constitutional doctrine
    — anyone who wants a different priority writes a different function,
    they do NOT alter this one.

    Priority (highest wins):

        1. ``typed.tenant_id`` (when ``typed`` is not None and its
           ``tenant_id`` axis is not None) — Wedge B2 typed-ingress
           is the canonical authority surface.
        2. ``legacy_tenant_id`` — pre-B2 ``str | None`` field.
           Coexistence invariants at every contract that carries
           both ``authority`` and ``tenant_id`` guarantee these two
           cannot disagree, so promoting legacy when typed is absent
           is constitutionally safe.
        3. ``observed_tenant_id`` — what the underlying execution
           observed (e.g., ``AgentExecutionTrace.tenant_id``). The
           fallback when no caller-stamped authority is available.
        4. ``None`` — fully tenantless. The operation has no
           authority chain at any axis.

    The returned ``AuthorityResolution`` records WHICH source won so
    callers can persist the attribution and replay can audit it
    without re-running this function.

    This function is PURE — no I/O, no global state, no wall-clock
    reads. Same inputs produce byte-identical outputs every call.
    """
    if typed is not None and typed.tenant_id is not None:
        return AuthorityResolution(
            tenant_id=typed.tenant_id,
            source=AuthoritySource.TYPED_AUTHORITY,
        )
    if legacy_tenant_id is not None:
        return AuthorityResolution(
            tenant_id=legacy_tenant_id,
            source=AuthoritySource.LEGACY_TENANT,
        )
    if observed_tenant_id is not None:
        return AuthorityResolution(
            tenant_id=observed_tenant_id,
            source=AuthoritySource.OBSERVED_TENANT,
        )
    return AuthorityResolution(
        tenant_id=None,
        source=AuthoritySource.NONE,
    )


__all__ = [
    "AuthorityContext",
    "AuthorityResolution",
    "AuthoritySource",
    "resolve_authority",
]
