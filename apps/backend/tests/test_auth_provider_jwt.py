"""``JWTProvider`` regression tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import pytest

from app.auth import (
    AuthenticationError,
    AuthProvider,
    Credential,
)
from app.auth.providers import (
    ClaimMapping,
    DEFAULT_CLAIM_MAPPING,
    JWTProvider,
)


HS_KEY = "97c01989a35cac67133239a913d2813c" "a7ca2e9bb779a18ad25e63ce518624bb"

HS512_KEY = (
    "97c01989a35cac67133239a913d2813c"
    "a7ca2e9bb779a18ad25e63ce518624bb"
    "2e005665a8e978adc63f833b5c5b0a83"
    "829b935feeded8878412cc55c9b1da35"
)

OTHER_HS_KEY = "c1d4e8a2f9b3c7d5e1a6b8f2c4d9e7a1" "f6b3d8c2a9e4f1b7d5c8a2e6f9b4d1c3"


def _encode(
    payload: dict[str, Any],
    *,
    key: str = HS_KEY,
    algorithm: str = "HS256",
) -> str:
    return jwt.encode(payload, key, algorithm=algorithm)


def _verify(provider: JWTProvider, token: str) -> Any:
    return asyncio.run(provider.verify(Credential(scheme="Bearer", value=token)))


def test_satisfies_authprovider_protocol() -> None:
    provider = JWTProvider(key=HS_KEY, algorithms=("HS256",))
    assert isinstance(provider, AuthProvider)


def test_name_defaults_to_jwt() -> None:
    provider = JWTProvider(key=HS_KEY, algorithms=("HS256",))
    assert provider.name == "jwt"


def test_custom_name_propagates() -> None:
    provider = JWTProvider(name="oidc", key=HS_KEY, algorithms=("HS256",))
    assert provider.name == "oidc"


def test_empty_algorithms_rejected_at_construction() -> None:
    with pytest.raises(ValueError):
        JWTProvider(key=HS_KEY, algorithms=())


def test_default_claim_mapping_pinned() -> None:
    assert DEFAULT_CLAIM_MAPPING == ClaimMapping(
        tenant_id="tenant_id",
        principal_id="sub",
        organization_id="org_id",
        environment_id="env",
    )


def test_valid_token_yields_verified_identity() -> None:
    token = _encode(
        {
            "sub": "alice",
            "tenant_id": "acme",
            "org_id": "org-7",
            "env": "prod",
        }
    )

    provider = JWTProvider(
        key=HS_KEY,
        algorithms=("HS256",),
    )

    vi = _verify(provider, token)

    assert vi.principal_id == "alice"
    assert vi.tenant_id == "acme"
    assert vi.organization_id == "org-7"
    assert vi.environment_id == "prod"
    assert vi.issuer == "jwt"
    assert vi.claims["sub"] == "alice"


def test_invalid_signature_raises() -> None:
    token = _encode(
        {"sub": "alice"},
        key=OTHER_HS_KEY,
    )

    provider = JWTProvider(
        key=HS_KEY,
        algorithms=("HS256",),
    )

    with pytest.raises(AuthenticationError):
        _verify(provider, token)


def test_missing_axis_claim_yields_none() -> None:
    token = _encode({"sub": "alice"})
    provider = JWTProvider(key=HS_KEY, algorithms=("HS256",))
    vi = _verify(provider, token)
    assert vi.principal_id == "alice"
    assert vi.tenant_id is None
    assert vi.organization_id is None
    assert vi.environment_id is None


def test_custom_claim_mapping() -> None:
    token = _encode({"https://example.com/tenant": "acme"})
    mapping = ClaimMapping(
        tenant_id="https://example.com/tenant",
        principal_id=None,
        organization_id=None,
        environment_id=None,
    )
    provider = JWTProvider(
        key=HS_KEY,
        algorithms=("HS256",),
        claim_mapping=mapping,
    )
    vi = _verify(provider, token)
    assert vi.tenant_id == "acme"
    assert vi.principal_id is None


def test_non_bearer_scheme_raises() -> None:
    provider = JWTProvider(key=HS_KEY, algorithms=("HS256",))
    with pytest.raises(AuthenticationError):
        asyncio.run(provider.verify(Credential(scheme="ApiKey", value="x")))


def test_expired_token_raises() -> None:
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    token = _encode({"sub": "alice", "exp": int(past.timestamp())})
    provider = JWTProvider(key=HS_KEY, algorithms=("HS256",))
    with pytest.raises(AuthenticationError):
        _verify(provider, token)


def test_unverified_algorithm_raises() -> None:
    token = _encode(
        {"sub": "alice"},
        key=HS512_KEY,
        algorithm="HS512",
    )

    provider = JWTProvider(
        key=HS_KEY,
        algorithms=("HS256",),
    )

    with pytest.raises(AuthenticationError):
        _verify(provider, token)


def test_issuer_allowlist_enforced() -> None:
    token = _encode({"sub": "alice", "iss": "bad-issuer"})
    provider = JWTProvider(
        key=HS_KEY,
        algorithms=("HS256",),
        issuer="trusted-issuer",
    )
    with pytest.raises(AuthenticationError):
        _verify(provider, token)


def test_issuer_match_passes() -> None:
    token = _encode({"sub": "alice", "iss": "trusted-issuer"})
    provider = JWTProvider(
        key=HS_KEY,
        algorithms=("HS256",),
        issuer="trusted-issuer",
    )
    vi = _verify(provider, token)
    assert vi.principal_id == "alice"


def test_audience_mismatch_raises() -> None:
    token = _encode({"sub": "alice", "aud": "other-svc"})
    provider = JWTProvider(
        key=HS_KEY,
        algorithms=("HS256",),
        audience="operious",
    )
    with pytest.raises(AuthenticationError):
        _verify(provider, token)


def test_audience_match_passes() -> None:
    token = _encode({"sub": "alice", "aud": "operious"})
    provider = JWTProvider(
        key=HS_KEY,
        algorithms=("HS256",),
        audience="operious",
    )
    vi = _verify(provider, token)
    assert vi.principal_id == "alice"


def test_required_claims_enforced() -> None:
    token = _encode({"sub": "alice"})
    provider = JWTProvider(
        key=HS_KEY,
        algorithms=("HS256",),
        require_claims=("tenant_id",),
    )
    with pytest.raises(AuthenticationError):
        _verify(provider, token)


def test_required_claims_satisfied() -> None:
    token = _encode({"sub": "alice", "tenant_id": "acme"})
    provider = JWTProvider(
        key=HS_KEY,
        algorithms=("HS256",),
        require_claims=("tenant_id",),
    )
    vi = _verify(provider, token)
    assert vi.tenant_id == "acme"


def test_non_string_axis_claim_raises() -> None:
    """Identity axes MUST be strings; coerce_*_id rejects non-strings
    downstream. Catch at the provider boundary."""
    token = _encode({"sub": "alice", "tenant_id": 12345})
    provider = JWTProvider(key=HS_KEY, algorithms=("HS256",))
    with pytest.raises(AuthenticationError):
        _verify(provider, token)


def test_exp_claim_propagates_to_expires_at() -> None:
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    token = _encode({"sub": "alice", "exp": int(future.timestamp())})
    provider = JWTProvider(key=HS_KEY, algorithms=("HS256",))
    vi = _verify(provider, token)
    assert vi.expires_at is not None
    assert (
        abs((vi.expires_at - future).total_seconds()) < 1.0
    )  # 1s tolerance for unix-int truncation
