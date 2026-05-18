"""Constitutional regression tests for ``app.identity.authority``.

Wedge B2 (Phase 1) pins the following invariants:

1. ``AuthorityContext`` is a frozen, slot-allocated value object — no
   mutation, no per-instance ``__dict__``, byte-equal across
   re-construction with the same components.
2. The default-constructed ``AuthorityContext`` is fully anonymous
   (every axis is ``None``) and is constitutionally distinct from
   any tenant-carrying authority.
3. ``AuthorityContext.from_raw`` is a validating gateway: it runs
   every supplied component through the ``coerce_*`` helper and
   rejects empty / whitespace-only / non-string input by raising
   ``IdentityError``.
4. ``from_raw`` strips whitespace symmetrically — ``"  acme  "`` and
   ``"acme"`` produce identical contexts. This is the discipline
   that prevents legacy "tenant" vs " tenant" drift.
5. ``is_tenantless`` and ``is_fully_anonymous`` predicate semantics
   match the value-object state without unwrapping fields, so
   policy code can branch on them without coupling to the field
   layout.
6. ``AuthorityContext`` is hashable and usable as a dictionary key
   (the prerequisite for future authority-keyed caches).
7. ``AuthorityContext`` is exported on the ``app.identity`` public
   surface so every sibling substrate imports the canonical type
   instead of redefining its own authority bag.

These tests are the constitutional contract that pins the foundation
laid by Wedge B2. Anyone who weakens these invariants — for example
by making ``from_raw`` silently accept empty strings or by exposing
a mutating setter — fails this entire file.
"""

from __future__ import annotations

import pytest

import app.identity as identity_pkg
from app.identity import (
    AuthorityContext,
    EnvironmentId,
    IdentityError,
    OrganizationId,
    PrincipalId,
    TenantId,
)


# ─── Shape: frozen, slotted, value-equal ─────────────────────────────


def test_authority_context_is_frozen() -> None:
    """Frozen dataclass — any field mutation must raise."""
    ctx = AuthorityContext(tenant_id=TenantId("acme"))
    with pytest.raises(Exception):
        ctx.tenant_id = TenantId("evil")  # type: ignore[misc]


def test_authority_context_is_slotted() -> None:
    """No per-instance ``__dict__`` — slots prevent attribute drift."""
    ctx = AuthorityContext()
    assert not hasattr(ctx, "__dict__")


def test_authority_context_is_value_equal() -> None:
    """Two contexts with identical components compare equal."""
    a = AuthorityContext(
        tenant_id=TenantId("acme"),
        principal_id=PrincipalId("p-1"),
        organization_id=OrganizationId("o-1"),
        environment_id=EnvironmentId("prod"),
    )
    b = AuthorityContext(
        tenant_id=TenantId("acme"),
        principal_id=PrincipalId("p-1"),
        organization_id=OrganizationId("o-1"),
        environment_id=EnvironmentId("prod"),
    )
    assert a == b
    assert hash(a) == hash(b)


def test_authority_context_default_is_fully_anonymous() -> None:
    """Default construction → every axis is ``None``."""
    ctx = AuthorityContext()
    assert ctx.tenant_id is None
    assert ctx.principal_id is None
    assert ctx.organization_id is None
    assert ctx.environment_id is None


# ─── Predicates ──────────────────────────────────────────────────────


def test_is_tenantless_true_when_tenant_id_is_none() -> None:
    ctx = AuthorityContext(principal_id=PrincipalId("p-1"))
    assert ctx.is_tenantless is True


def test_is_tenantless_false_when_tenant_id_is_set() -> None:
    ctx = AuthorityContext(tenant_id=TenantId("acme"))
    assert ctx.is_tenantless is False


def test_is_fully_anonymous_true_only_when_all_axes_none() -> None:
    assert AuthorityContext().is_fully_anonymous is True
    assert (
        AuthorityContext(
            tenant_id=TenantId("acme")
        ).is_fully_anonymous
        is False
    )
    assert (
        AuthorityContext(
            principal_id=PrincipalId("p-1")
        ).is_fully_anonymous
        is False
    )
    assert (
        AuthorityContext(
            organization_id=OrganizationId("o-1")
        ).is_fully_anonymous
        is False
    )
    assert (
        AuthorityContext(
            environment_id=EnvironmentId("prod")
        ).is_fully_anonymous
        is False
    )


# ─── from_raw validation gateway ─────────────────────────────────────


def test_from_raw_constructs_via_coerce_helpers() -> None:
    ctx = AuthorityContext.from_raw(
        tenant_id="acme",
        principal_id="p-1",
        organization_id="o-1",
        environment_id="prod",
    )
    assert ctx.tenant_id == "acme"
    assert ctx.principal_id == "p-1"
    assert ctx.organization_id == "o-1"
    assert ctx.environment_id == "prod"


def test_from_raw_strips_whitespace_on_every_axis() -> None:
    """Symmetry with the underlying ``coerce_*`` helpers."""
    a = AuthorityContext.from_raw(
        tenant_id="  acme  ",
        principal_id="\tp-1\n",
        organization_id="  o-1",
        environment_id="prod  ",
    )
    b = AuthorityContext.from_raw(
        tenant_id="acme",
        principal_id="p-1",
        organization_id="o-1",
        environment_id="prod",
    )
    assert a == b


def test_from_raw_with_no_args_produces_fully_anonymous() -> None:
    ctx = AuthorityContext.from_raw()
    assert ctx.is_fully_anonymous is True


def test_from_raw_preserves_none_per_axis() -> None:
    """A ``None`` component is the explicit "no authority on this
    axis" channel — it must not be coerced or rejected."""
    ctx = AuthorityContext.from_raw(tenant_id="acme")
    assert ctx.tenant_id == "acme"
    assert ctx.principal_id is None
    assert ctx.organization_id is None
    assert ctx.environment_id is None


@pytest.mark.parametrize(
    "axis",
    [
        "tenant_id",
        "principal_id",
        "organization_id",
        "environment_id",
    ],
)
def test_from_raw_rejects_empty_string_on_every_axis(axis: str) -> None:
    """``""`` is constitutionally distinct from ``None`` AND is an
    invalid identifier — ``coerce_*`` must reject it on every axis."""
    with pytest.raises(IdentityError):
        AuthorityContext.from_raw(**{axis: ""})


@pytest.mark.parametrize(
    "axis",
    [
        "tenant_id",
        "principal_id",
        "organization_id",
        "environment_id",
    ],
)
def test_from_raw_rejects_whitespace_only_on_every_axis(
    axis: str,
) -> None:
    with pytest.raises(IdentityError):
        AuthorityContext.from_raw(**{axis: "   "})


@pytest.mark.parametrize(
    "axis",
    [
        "tenant_id",
        "principal_id",
        "organization_id",
        "environment_id",
    ],
)
def test_from_raw_rejects_non_string_on_every_axis(axis: str) -> None:
    with pytest.raises(IdentityError):
        AuthorityContext.from_raw(**{axis: 42})  # type: ignore[arg-type]


# ─── Hashability (prerequisite for authority-keyed caches) ───────────


def test_authority_context_is_hashable() -> None:
    ctx = AuthorityContext(tenant_id=TenantId("acme"))
    assert hash(ctx) == hash(ctx)


def test_authority_contexts_usable_as_dict_keys() -> None:
    a = AuthorityContext(tenant_id=TenantId("acme"))
    b = AuthorityContext(tenant_id=TenantId("beta"))
    bucket: dict[AuthorityContext, int] = {a: 1, b: 2}
    assert bucket[a] == 1
    assert bucket[b] == 2
    # Re-construct ``a`` independently; same components must collide
    # to the same bucket entry.
    assert bucket[AuthorityContext(tenant_id=TenantId("acme"))] == 1


def test_distinct_authority_contexts_compare_unequal() -> None:
    """Two contexts that differ on any single axis must NOT compare
    equal — that is the constitutional non-collapse invariant for
    authority distinguishability."""
    base = AuthorityContext(
        tenant_id=TenantId("acme"),
        principal_id=PrincipalId("p-1"),
    )
    assert base != AuthorityContext(
        tenant_id=TenantId("acme"),
        principal_id=PrincipalId("p-2"),
    )
    assert base != AuthorityContext(
        tenant_id=TenantId("beta"),
        principal_id=PrincipalId("p-1"),
    )
    assert base != AuthorityContext(
        tenant_id=TenantId("acme"),
        principal_id=PrincipalId("p-1"),
        organization_id=OrganizationId("o-1"),
    )


def test_tenant_none_distinct_from_tenant_empty_via_coerce_path() -> (
    None
):
    """``tenant_id=None`` is the validly-anonymous case; ``""`` is a
    rejected input on the ``coerce_*`` path. The two states cannot
    BOTH inhabit a validly-constructed ``AuthorityContext``."""
    anonymous = AuthorityContext.from_raw()
    with pytest.raises(IdentityError):
        AuthorityContext.from_raw(tenant_id="")
    # The validly-anonymous case must remain accessible.
    assert anonymous.tenant_id is None


# ─── Public surface ──────────────────────────────────────────────────


def test_authority_context_is_exported_from_identity_substrate() -> (
    None
):
    """``AuthorityContext`` must be available on the ``app.identity``
    public surface so every ingress surface imports the canonical
    value object instead of defining a private authority bag."""
    assert hasattr(identity_pkg, "AuthorityContext")
    assert "AuthorityContext" in identity_pkg.__all__
    assert identity_pkg.AuthorityContext is AuthorityContext
