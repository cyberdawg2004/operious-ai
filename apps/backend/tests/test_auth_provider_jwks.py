"""PR-C1 tests for ``JWKSAuthProvider``.

Offline-deterministic: every test generates a fresh RSA-2048
keypair, builds an in-memory JWK set, injects a
:class:`PyJWKClient`-compatible test client via
:meth:`JWKSAuthProvider.with_jwk_client`, and never contacts the
network. The contract under test is identical to what the
production provider exercises against Auth0 — only the JWKS
transport differs.

Pinned contract:

* RS256 verification round-trips when issuer + audience + ``kid``
  all match the published JWKS.
* Every failure mode (wrong signature, wrong audience, wrong
  issuer, expired, unknown ``kid``, missing ``kid`` header,
  wrong algorithm, bad scheme) raises
  :class:`AuthenticationError`.
* Claim mapping projects ``sub`` / ``tenant_id`` / etc. into
  :class:`VerifiedIdentity`; namespaced custom claims work via
  a custom :class:`ClaimMapping`.
* :meth:`with_jwk_client` accepts an injected JWK client so tests
  can exercise token verification without an external JWKS service.
* Constructor validation: empty audience / empty issuer / empty
  algorithms / ``"none"`` algorithm all raise ``ValueError``.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, cast

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWK, PyJWKClient, PyJWKClientError
from jwt.algorithms import RSAAlgorithm

from app.auth.credentials import Credential
from app.auth.errors import AuthenticationError
from app.auth.identity import VerifiedIdentity
from app.auth.providers import (
    ClaimMapping,
    JWKSAuthProvider,
)
from app.auth.protocols import AuthProvider


# ─── Fixtures: in-memory JWKS + keypair ──────────────────────────────────


def _generate_rsa_keypair() -> tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]:
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    return private_key, private_key.public_key()


def _jwk_from_public_key(
    public_key: rsa.RSAPublicKey, *, kid: str
) -> dict[str, Any]:
    """Build a single RSA JWK dict from a public key."""
    jwk_json = RSAAlgorithm.to_jwk(public_key)
    jwk = json.loads(jwk_json)
    jwk["kid"] = kid
    jwk["use"] = "sig"
    jwk["alg"] = "RS256"
    return jwk


class _SigningKey:
    def __init__(self, key: Any) -> None:
        self.key = key


class _InMemoryJWKClient:
    uri = "memory://test-jwks"

    def __init__(self, jwks: dict[str, Any]) -> None:
        self._keys: dict[str, Any] = {}
        for jwk in jwks.get("keys", []):
            if not isinstance(jwk, dict):
                continue
            kid = jwk.get("kid")
            if isinstance(kid, str):
                self._keys[kid] = PyJWK.from_dict(jwk).key

    def get_signing_key_from_jwt(self, token: str) -> _SigningKey:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not isinstance(kid, str):
            raise PyJWKClientError("JWT header is missing a string kid")
        key = self._keys.get(kid)
        if key is None:
            raise PyJWKClientError(
                f"Unable to find a signing key that matches: {kid!r}"
            )
        return _SigningKey(key)


def _build_provider(
    tmp_path: Path,
    *,
    public_key: rsa.RSAPublicKey,
    kid: str,
    audience: str | tuple[str, ...] = "https://api.operious.ai",
    issuer: str | tuple[str, ...] = "https://operious-dev.auth0.com/",
    claim_mapping: ClaimMapping | None = None,
    leeway: float = 0.0,
) -> JWKSAuthProvider:
    """Construct a JWKSAuthProvider backed by an in-memory JWKS."""
    del tmp_path
    jwks = {"keys": [_jwk_from_public_key(public_key, kid=kid)]}
    jwk_client = cast(PyJWKClient, _InMemoryJWKClient(jwks))
    return JWKSAuthProvider.with_jwk_client(
        jwk_client=jwk_client,
        audience=audience,
        issuer=issuer,
        algorithms=("RS256",),
        name="auth0",
        leeway=leeway,
        claim_mapping=claim_mapping
        if claim_mapping is not None
        else ClaimMapping(),
    )


def _encode_rs256(
    private_key: rsa.RSAPrivateKey,
    *,
    kid: str,
    claims: dict[str, Any],
) -> str:
    """Sign a JWT with the private half of the JWKS keypair."""
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return jwt.encode(
        claims,
        private_pem,
        algorithm="RS256",
        headers={"kid": kid},
    )


def _verify(provider: JWKSAuthProvider, token: str) -> VerifiedIdentity:
    return asyncio.run(
        provider.verify(Credential(scheme="Bearer", value=token))
    )


# ─── Constructor validation ──────────────────────────────────────────────


def test_constructor_requires_jwks_uri() -> None:
    with pytest.raises(ValueError, match="jwks_uri"):
        JWKSAuthProvider(
            jwks_uri="",
            audience="aud",
            issuer="iss",
        )


def test_constructor_requires_audience() -> None:
    with pytest.raises(ValueError, match="audience"):
        JWKSAuthProvider(
            jwks_uri="https://example.invalid/.well-known/jwks.json",
            audience="",
            issuer="iss",
        )


def test_constructor_requires_issuer() -> None:
    with pytest.raises(ValueError, match="issuer"):
        JWKSAuthProvider(
            jwks_uri="https://example.invalid/.well-known/jwks.json",
            audience="aud",
            issuer="",
        )


def test_constructor_refuses_none_algorithm() -> None:
    with pytest.raises(ValueError, match="none"):
        JWKSAuthProvider(
            jwks_uri="https://example.invalid/.well-known/jwks.json",
            audience="aud",
            issuer="iss",
            algorithms=("none",),
        )


def test_constructor_requires_non_empty_algorithms() -> None:
    with pytest.raises(ValueError, match="algorithms"):
        JWKSAuthProvider(
            jwks_uri="https://example.invalid/.well-known/jwks.json",
            audience="aud",
            issuer="iss",
            algorithms=(),
        )


def test_satisfies_authprovider_protocol(tmp_path: Path) -> None:
    private, public = _generate_rsa_keypair()
    provider = _build_provider(tmp_path, public_key=public, kid="k1")
    assert isinstance(provider, AuthProvider)
    # Reference the private key so the keypair stays alive long
    # enough to be used by any subsequent test in this module if
    # someone extends the fixture later.
    _ = private


# ─── Happy path ──────────────────────────────────────────────────────────


def test_valid_token_yields_verified_identity(tmp_path: Path) -> None:
    private, public = _generate_rsa_keypair()
    provider = _build_provider(tmp_path, public_key=public, kid="k1")
    now = int(time.time())
    token = _encode_rs256(
        private,
        kid="k1",
        claims={
            "sub": "user-123",
            "tenant_id": "tenant-acme",
            "org_id": "org-1",
            "env": "prod",
            "capabilities": ["read", "write"],
            "iss": "https://operious-dev.auth0.com/",
            "aud": "https://api.operious.ai",
            "iat": now,
            "exp": now + 3600,
        },
    )

    identity = _verify(provider, token)

    assert identity.tenant_id == "tenant-acme"
    assert identity.principal_id == "user-123"
    assert identity.organization_id == "org-1"
    assert identity.environment_id == "prod"
    assert identity.capabilities == frozenset({"read", "write"})
    assert identity.issuer == "auth0"
    assert identity.expires_at is not None
    assert "iat" in identity.claims


def test_custom_claim_mapping_handles_namespaced_auth0_claims(
    tmp_path: Path,
) -> None:
    """Auth0 namespaces custom claims under URI-shaped keys. The
    substrate's :class:`ClaimMapping` supports arbitrary claim
    names, so namespaced custom claims work without provider
    changes."""
    private, public = _generate_rsa_keypair()
    mapping = ClaimMapping(
        tenant_id="https://operious.ai/tenant_id",
        principal_id="sub",
        organization_id="https://operious.ai/org_id",
        environment_id="https://operious.ai/env",
        capabilities="https://operious.ai/permissions",
    )
    provider = _build_provider(
        tmp_path,
        public_key=public,
        kid="k1",
        claim_mapping=mapping,
    )
    now = int(time.time())
    token = _encode_rs256(
        private,
        kid="k1",
        claims={
            "sub": "user-456",
            "https://operious.ai/tenant_id": "tenant-beta",
            "https://operious.ai/org_id": "org-2",
            "https://operious.ai/env": "staging",
            "https://operious.ai/permissions": ["read"],
            "iss": "https://operious-dev.auth0.com/",
            "aud": "https://api.operious.ai",
            "iat": now,
            "exp": now + 3600,
        },
    )

    identity = _verify(provider, token)
    assert identity.tenant_id == "tenant-beta"
    assert identity.organization_id == "org-2"
    assert identity.environment_id == "staging"
    assert identity.capabilities == frozenset({"read"})


def test_capabilities_accepts_space_separated_string(
    tmp_path: Path,
) -> None:
    """OAuth2 ``scope`` style — single space-separated string."""
    private, public = _generate_rsa_keypair()
    provider = _build_provider(tmp_path, public_key=public, kid="k1")
    now = int(time.time())
    token = _encode_rs256(
        private,
        kid="k1",
        claims={
            "sub": "user-1",
            "capabilities": "read write admin",
            "iss": "https://operious-dev.auth0.com/",
            "aud": "https://api.operious.ai",
            "iat": now,
            "exp": now + 60,
        },
    )

    identity = _verify(provider, token)
    assert identity.capabilities == frozenset({"read", "write", "admin"})


# ─── Failure modes ───────────────────────────────────────────────────────


def test_rejects_non_bearer_credential(tmp_path: Path) -> None:
    _, public = _generate_rsa_keypair()
    provider = _build_provider(tmp_path, public_key=public, kid="k1")
    with pytest.raises(AuthenticationError, match="Bearer"):
        asyncio.run(
            provider.verify(Credential(scheme="Basic", value="abc"))
        )


def test_rejects_token_with_wrong_signature(tmp_path: Path) -> None:
    _, public = _generate_rsa_keypair()
    other_private, _ = _generate_rsa_keypair()
    provider = _build_provider(tmp_path, public_key=public, kid="k1")
    now = int(time.time())
    token = _encode_rs256(
        other_private,  # signed with a different private key!
        kid="k1",
        claims={
            "sub": "user-1",
            "iss": "https://operious-dev.auth0.com/",
            "aud": "https://api.operious.ai",
            "iat": now,
            "exp": now + 60,
        },
    )
    with pytest.raises(AuthenticationError, match="invalid token"):
        _verify(provider, token)


def test_rejects_token_with_wrong_audience(tmp_path: Path) -> None:
    private, public = _generate_rsa_keypair()
    provider = _build_provider(tmp_path, public_key=public, kid="k1")
    now = int(time.time())
    token = _encode_rs256(
        private,
        kid="k1",
        claims={
            "sub": "user-1",
            "iss": "https://operious-dev.auth0.com/",
            "aud": "https://attacker.example/api",
            "iat": now,
            "exp": now + 60,
        },
    )
    with pytest.raises(AuthenticationError, match="audience"):
        _verify(provider, token)


def test_rejects_token_with_wrong_issuer(tmp_path: Path) -> None:
    private, public = _generate_rsa_keypair()
    provider = _build_provider(tmp_path, public_key=public, kid="k1")
    now = int(time.time())
    token = _encode_rs256(
        private,
        kid="k1",
        claims={
            "sub": "user-1",
            "iss": "https://attacker.example/",
            "aud": "https://api.operious.ai",
            "iat": now,
            "exp": now + 60,
        },
    )
    with pytest.raises(AuthenticationError, match="issuer"):
        _verify(provider, token)


def test_rejects_expired_token(tmp_path: Path) -> None:
    private, public = _generate_rsa_keypair()
    provider = _build_provider(tmp_path, public_key=public, kid="k1")
    now = int(time.time())
    token = _encode_rs256(
        private,
        kid="k1",
        claims={
            "sub": "user-1",
            "iss": "https://operious-dev.auth0.com/",
            "aud": "https://api.operious.ai",
            "iat": now - 7200,
            "exp": now - 3600,  # expired one hour ago
        },
    )
    with pytest.raises(AuthenticationError, match="invalid token"):
        _verify(provider, token)


def test_rejects_token_with_unknown_kid(tmp_path: Path) -> None:
    private, public = _generate_rsa_keypair()
    # JWKS publishes only kid="known"; token signed with kid="unknown".
    provider = _build_provider(tmp_path, public_key=public, kid="known")
    now = int(time.time())
    token = _encode_rs256(
        private,
        kid="unknown",
        claims={
            "sub": "user-1",
            "iss": "https://operious-dev.auth0.com/",
            "aud": "https://api.operious.ai",
            "iat": now,
            "exp": now + 60,
        },
    )
    with pytest.raises(AuthenticationError, match="JWKS"):
        _verify(provider, token)


def test_rejects_token_without_kid_header(tmp_path: Path) -> None:
    private, public = _generate_rsa_keypair()
    provider = _build_provider(tmp_path, public_key=public, kid="k1")
    now = int(time.time())
    # Build token WITHOUT a kid header — PyJWT permits this at sign
    # time, but the JWKS resolver has no way to pick a key.
    private_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    token = jwt.encode(
        {
            "sub": "user-1",
            "iss": "https://operious-dev.auth0.com/",
            "aud": "https://api.operious.ai",
            "iat": now,
            "exp": now + 60,
        },
        private_pem,
        algorithm="RS256",
    )
    with pytest.raises(AuthenticationError):
        _verify(provider, token)


def test_rejects_token_with_non_string_claim(tmp_path: Path) -> None:
    private, public = _generate_rsa_keypair()
    provider = _build_provider(tmp_path, public_key=public, kid="k1")
    now = int(time.time())
    token = _encode_rs256(
        private,
        kid="k1",
        claims={
            "sub": "user-1",
            "tenant_id": 12345,  # not a string — invalid axis value
            "iss": "https://operious-dev.auth0.com/",
            "aud": "https://api.operious.ai",
            "iat": now,
            "exp": now + 60,
        },
    )
    with pytest.raises(AuthenticationError, match="tenant_id"):
        _verify(provider, token)


def test_required_claim_missing_raises(tmp_path: Path) -> None:
    private, public = _generate_rsa_keypair()
    del tmp_path
    jwks = {"keys": [_jwk_from_public_key(public, kid="k1")]}
    jwk_client = cast(PyJWKClient, _InMemoryJWKClient(jwks))
    provider = JWKSAuthProvider.with_jwk_client(
        jwk_client=jwk_client,
        audience="https://api.operious.ai",
        issuer="https://operious-dev.auth0.com/",
        require_claims=("custom_required",),
    )
    now = int(time.time())
    token = _encode_rs256(
        private,
        kid="k1",
        claims={
            "sub": "user-1",
            "iss": "https://operious-dev.auth0.com/",
            "aud": "https://api.operious.ai",
            "iat": now,
            "exp": now + 60,
        },
    )
    with pytest.raises(AuthenticationError, match="custom_required"):
        _verify(provider, token)
