"""``StaticTokenProvider`` regression tests."""

from __future__ import annotations

import asyncio

import pytest

from app.auth import (
    AuthenticationError,
    AuthProvider,
    Credential,
    VerifiedIdentity,
)
from app.auth.providers import StaticTokenProvider


def _verify(provider: StaticTokenProvider, cred: Credential) -> VerifiedIdentity:
    return asyncio.run(provider.verify(cred))


def test_satisfies_authprovider_protocol() -> None:
    provider = StaticTokenProvider(tokens={})
    assert isinstance(provider, AuthProvider)


def test_name_is_stable() -> None:
    assert StaticTokenProvider.name == "static_token"


def test_known_token_returns_identity() -> None:
    identity = VerifiedIdentity(tenant_id="acme", principal_id="alice")
    provider = StaticTokenProvider(tokens={"tok1": identity})
    vi = _verify(provider, Credential(scheme="Bearer", value="tok1"))
    assert vi.tenant_id == "acme"
    assert vi.principal_id == "alice"


def test_unknown_token_raises() -> None:
    provider = StaticTokenProvider(tokens={})
    with pytest.raises(AuthenticationError):
        _verify(provider, Credential(scheme="Bearer", value="missing"))


def test_non_bearer_scheme_raises() -> None:
    provider = StaticTokenProvider(
        tokens={"tok": VerifiedIdentity(tenant_id="acme")}
    )
    with pytest.raises(AuthenticationError):
        _verify(provider, Credential(scheme="ApiKey", value="tok"))


def test_bearer_scheme_case_insensitive() -> None:
    provider = StaticTokenProvider(
        tokens={"tok": VerifiedIdentity(tenant_id="acme")}
    )
    for scheme in ("Bearer", "bearer", "BEARER", "BeArEr"):
        vi = _verify(provider, Credential(scheme=scheme, value="tok"))
        assert vi.tenant_id == "acme"


def test_stamps_issuer_when_absent() -> None:
    provider = StaticTokenProvider(
        tokens={"tok": VerifiedIdentity(tenant_id="acme")}
    )
    vi = _verify(provider, Credential(scheme="Bearer", value="tok"))
    assert vi.issuer == "static_token"


def test_preserves_issuer_when_set() -> None:
    identity = VerifiedIdentity(tenant_id="acme", issuer="explicit")
    provider = StaticTokenProvider(tokens={"tok": identity})
    vi = _verify(provider, Credential(scheme="Bearer", value="tok"))
    assert vi.issuer == "explicit"


def test_stamps_issued_at_when_absent() -> None:
    provider = StaticTokenProvider(
        tokens={"tok": VerifiedIdentity(tenant_id="acme")}
    )
    vi = _verify(provider, Credential(scheme="Bearer", value="tok"))
    assert vi.issued_at is not None


def test_custom_issuer_name() -> None:
    provider = StaticTokenProvider(
        tokens={"tok": VerifiedIdentity(tenant_id="acme")},
        issuer="dev-fixture",
    )
    vi = _verify(provider, Credential(scheme="Bearer", value="tok"))
    assert vi.issuer == "dev-fixture"


def test_construction_is_defensive_copy() -> None:
    """Caller mutation of the source mapping after construction
    must not affect the provider (preserves determinism)."""
    source: dict[str, VerifiedIdentity] = {
        "tok": VerifiedIdentity(tenant_id="acme")
    }
    provider = StaticTokenProvider(tokens=source)
    source.clear()
    vi = _verify(provider, Credential(scheme="Bearer", value="tok"))
    assert vi.tenant_id == "acme"
