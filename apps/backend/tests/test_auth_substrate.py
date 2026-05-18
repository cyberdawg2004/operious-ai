"""Constitutional regression tests for the ``app.auth`` substrate
(Branch C / Wedge C1).

Pins:

1. public API surface,
2. ``AuthenticationError`` vs :class:`app.identity.IdentityError`
   are distinct categories,
3. ``Credential`` is frozen + value-equal,
4. ``VerifiedIdentity`` is frozen, every axis optional, audit
   attribution preserved,
5. translator routes through ``AuthorityContext.from_raw``
   (whitespace stripped, malformed raises ``IdentityError``,
   empty identity → empty authority, determinism),
6. ``AuthProvider`` is ``runtime_checkable`` and refuses incomplete
   duck types,
7. ``NullAuthProvider`` rejects every credential (fail-closed
   default),
8. substrate leaf-up-one invariant — only imports from
   ``app.identity`` and stdlib.
"""

from __future__ import annotations

import asyncio
import dataclasses
import pathlib
from datetime import datetime, timezone

import pytest

import app.auth as auth_pkg
from app.auth import (
    AuthProvider,
    AuthenticationError,
    Credential,
    NullAuthProvider,
    VerifiedIdentity,
    verified_identity_to_authority,
)
from app.identity import AuthorityContext, IdentityError


# ─── Surface ────────────────────────────────────────────────────────


def test_public_api_surface_is_stable() -> None:
    assert set(auth_pkg.__all__) == {
        "AuthProvider",
        "AuthenticationError",
        "Credential",
        "NullAuthProvider",
        "VerifiedIdentity",
        "verified_identity_to_authority",
    }


# ─── Errors ─────────────────────────────────────────────────────────


def test_authentication_error_is_exception() -> None:
    assert issubclass(AuthenticationError, Exception)


def test_authentication_error_disjoint_from_identity_error() -> None:
    """Two distinct constitutional categories — auth refusal vs
    typed primitive malformation. Conflating them collapses audit
    semantics."""
    assert not issubclass(AuthenticationError, IdentityError)
    assert not issubclass(IdentityError, AuthenticationError)


# ─── Credential ─────────────────────────────────────────────────────


def test_credential_is_frozen() -> None:
    cred = Credential(scheme="Bearer", value="abc")
    with pytest.raises(dataclasses.FrozenInstanceError):
        cred.scheme = "ApiKey"  # type: ignore[misc]


def test_credential_equality_by_value() -> None:
    a = Credential(scheme="Bearer", value="abc")
    b = Credential(scheme="Bearer", value="abc")
    c = Credential(scheme="Bearer", value="xyz")
    assert a == b
    assert a != c


# ─── VerifiedIdentity ───────────────────────────────────────────────


def test_verified_identity_all_axes_default_to_none() -> None:
    vi = VerifiedIdentity()
    assert vi.tenant_id is None
    assert vi.principal_id is None
    assert vi.organization_id is None
    assert vi.environment_id is None
    assert vi.issuer is None
    assert vi.issued_at is None
    assert vi.expires_at is None
    assert vi.claims == {}


def test_verified_identity_is_frozen() -> None:
    vi = VerifiedIdentity(tenant_id="acme")
    with pytest.raises(dataclasses.FrozenInstanceError):
        vi.tenant_id = "other"  # type: ignore[misc]


def test_verified_identity_carries_audit_attribution() -> None:
    now = datetime.now(timezone.utc)
    vi = VerifiedIdentity(
        tenant_id="acme",
        issuer="oidc-provider",
        issued_at=now,
        expires_at=now,
        claims={"sub": "user-1", "scope": "read"},
    )
    assert vi.issuer == "oidc-provider"
    assert vi.issued_at is now
    assert vi.expires_at is now
    assert vi.claims == {"sub": "user-1", "scope": "read"}


# ─── Translator ─────────────────────────────────────────────────────


def test_translator_routes_through_from_raw() -> None:
    vi = VerifiedIdentity(
        tenant_id="acme",
        principal_id="user-1",
        organization_id="org-7",
        environment_id="prod",
        issuer="x",
    )
    ctx = verified_identity_to_authority(vi)
    assert isinstance(ctx, AuthorityContext)
    assert ctx.tenant_id == "acme"
    assert ctx.principal_id == "user-1"
    assert ctx.organization_id == "org-7"
    assert ctx.environment_id == "prod"


def test_translator_strips_whitespace_via_coerce() -> None:
    vi = VerifiedIdentity(
        tenant_id="  acme  ",
        principal_id="\tuser-1\n",
    )
    ctx = verified_identity_to_authority(vi)
    assert ctx.tenant_id == "acme"
    assert ctx.principal_id == "user-1"


def test_translator_does_not_propagate_audit_to_authority() -> None:
    """Identity surface ≠ verification surface. Callers that need
    provenance hold the ``VerifiedIdentity`` separately."""
    vi = VerifiedIdentity(
        tenant_id="acme",
        issuer="provider-x",
        claims={"scope": "read"},
    )
    ctx = verified_identity_to_authority(vi)
    assert not hasattr(ctx, "issuer")
    assert not hasattr(ctx, "claims")
    assert not hasattr(ctx, "issued_at")


@pytest.mark.parametrize(
    "vi",
    [
        VerifiedIdentity(tenant_id="   "),
        VerifiedIdentity(principal_id="   "),
        VerifiedIdentity(organization_id="   "),
        VerifiedIdentity(environment_id="   "),
    ],
    ids=["tenant_id", "principal_id", "organization_id", "environment_id"],
)
def test_translator_rejects_malformed_axis(vi: VerifiedIdentity) -> None:
    """Whitespace-only verified claim is structurally malformed
    once it reaches the typed surface. Substrate does NOT swallow
    — propagates ``IdentityError`` per Wedge A doctrine."""
    with pytest.raises(IdentityError):
        verified_identity_to_authority(vi)


def test_translator_empty_identity_yields_empty_authority() -> None:
    ctx = verified_identity_to_authority(VerifiedIdentity())
    assert ctx.tenant_id is None
    assert ctx.principal_id is None
    assert ctx.organization_id is None
    assert ctx.environment_id is None


def test_translator_is_deterministic() -> None:
    """Same input → byte-equal output (ingress replay
    determinism)."""
    vi = VerifiedIdentity(
        tenant_id="acme",
        principal_id="user-1",
        organization_id="org-7",
        environment_id="prod",
    )
    a = verified_identity_to_authority(vi)
    b = verified_identity_to_authority(vi)
    assert a == b


# ─── AuthProvider protocol ──────────────────────────────────────────


def test_auth_provider_is_runtime_checkable() -> None:
    assert isinstance(NullAuthProvider(), AuthProvider)


def test_incomplete_implementation_is_not_authprovider() -> None:
    class Incomplete:
        pass

    assert not isinstance(Incomplete(), AuthProvider)


# ─── NullAuthProvider ───────────────────────────────────────────────


def test_null_provider_name_is_stable() -> None:
    assert NullAuthProvider.name == "null"
    assert NullAuthProvider().name == "null"


def test_null_provider_rejects_every_credential() -> None:
    provider = NullAuthProvider()
    with pytest.raises(AuthenticationError):
        asyncio.run(
            provider.verify(Credential(scheme="Bearer", value="x"))
        )


def test_null_provider_rejects_any_scheme() -> None:
    provider = NullAuthProvider()
    for scheme in ("Bearer", "ApiKey", "mTLS", "Basic", "Unknown"):
        with pytest.raises(AuthenticationError):
            asyncio.run(
                provider.verify(Credential(scheme=scheme, value="x"))
            )


# ─── Leaf-up-one invariant ──────────────────────────────────────────


def test_auth_substrate_imports_only_identity() -> None:
    """``app.auth`` may import ONLY from ``app.identity`` and
    stdlib. Any other sibling import inverts intended dependency
    direction and breaks substrate isolation."""
    forbidden_prefixes = (
        "app.governance",
        "app.session",
        "app.hardening",
        "app.arbitration",
        "app.boundary",
        "app.coordination",
        "app.agents",
        "app.supervisor",
        "app.organizational_intelligence",
        "app.api",
        "app.services",
        "app.repositories",
        "app.db",
        "app.middleware",
        "app.observability",
        "app.dependencies",
        "app.core",
    )
    auth_init = auth_pkg.__file__
    assert auth_init is not None, "app.auth must be a package"
    auth_root = pathlib.Path(auth_init).parent
    for py_file in auth_root.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for forbidden in forbidden_prefixes:
            assert f"from {forbidden}" not in text, (
                f"{py_file} imports from forbidden sibling "
                f"substrate {forbidden}"
            )
            assert f"import {forbidden}" not in text, (
                f"{py_file} imports forbidden sibling substrate "
                f"{forbidden}"
            )
