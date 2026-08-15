"""PR-D1 tests for ``GET /v1/auth/me``.

End-to-end: real :class:`AuthorityContextMiddleware`, real
:class:`JWKSAuthProvider`, real :func:`require_authority`
dependency, real FastAPI router. The only thing replaced is the
JWKS transport — instead of fetching from Auth0 over the
network, each test generates a fresh RSA-2048 keypair and injects
a :class:`PyJWKClient`-compatible in-memory client.

Pinned contract:

* Anonymous request → 401 ``authority_required``.
* Verified Bearer token → 200 with the principal data and
  ``authority_source = "verified"``.
* Verified Bearer token with no tenant claim and no
  ``platform.tenant.admin`` → 403 ``authorized_scope_required``.
* Invalid signature / wrong audience / wrong issuer / expired →
  401 ``verification_failed`` (every failure mode the middleware
  must convert into a uniform refusal).
* Malformed Authorization header → 400 ``malformed_authorization_header``.
* Conflict between Authorization and ``X-*-ID`` → 400
  ``authority_source_conflict``.
* Legacy ``X-Tenant-ID`` (no Authorization, anonymous mode) →
  200 with ``authority_source = "header"``.
* Capabilities are sorted lexicographically in the response so
  two requests with identical authorities produce byte-equal
  JSON.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import jwt
import httpx
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWK, PyJWKClient, PyJWKClientError
from jwt.algorithms import RSAAlgorithm

# ``app.main`` creates the module-level application at import time.  Keep this
# isolated router suite offline before importing it; no test should enqueue a
# Sentry delivery or wait on its retry backoff.
os.environ["SENTRY_DSN"] = ""

from app.auth.providers import JWKSAuthProvider
from app.core.config import get_settings
from app.main import create_app

# ─── Fixtures: JWKS + signing helpers (mirror test_auth_provider_jwks) ──


def _generate_rsa_keypair() -> tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]:
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    return private_key, private_key.public_key()


def _jwk_from_public_key(
    public_key: rsa.RSAPublicKey, *, kid: str
) -> dict[str, Any]:
    jwk = json.loads(RSAAlgorithm.to_jwk(public_key))
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


_TEST_ISSUER = "https://operious-test.auth0.com/"
_TEST_AUDIENCE = "https://api.operious.test"


def _build_jwks_provider(
    tmp_path: Path, *, public_key: rsa.RSAPublicKey, kid: str
) -> JWKSAuthProvider:
    del tmp_path
    jwks = {"keys": [_jwk_from_public_key(public_key, kid=kid)]}
    jwk_client = cast(PyJWKClient, _InMemoryJWKClient(jwks))
    return JWKSAuthProvider.with_jwk_client(
        jwk_client=jwk_client,
        audience=_TEST_AUDIENCE,
        issuer=_TEST_ISSUER,
        algorithms=("RS256",),
        name="auth0_test",
    )


def _sign_rs256(
    private: rsa.RSAPrivateKey,
    *,
    kid: str,
    claims: dict[str, Any],
) -> str:
    pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return jwt.encode(
        claims, pem, algorithm="RS256", headers={"kid": kid}
    )


def _standard_claims(
    *,
    sub: str = "auth0|user-123",
    tenant_id: str | None = "tenant-acme",
    organization_id: str | None = "org-1",
    environment_id: str | None = "production",
    capabilities: list[str] | None = None,
    issuer: str = _TEST_ISSUER,
    audience: str = _TEST_AUDIENCE,
    exp_delta_seconds: int = 3600,
) -> dict[str, Any]:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": sub,
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + exp_delta_seconds,
    }
    if tenant_id is not None:
        claims["tenant_id"] = tenant_id
    if organization_id is not None:
        claims["org_id"] = organization_id
    if environment_id is not None:
        claims["env"] = environment_id
    if capabilities is not None:
        claims["capabilities"] = capabilities
    return claims


@pytest_asyncio.fixture
async def keypair_and_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[rsa.RSAPrivateKey, str, httpx.AsyncClient]]:
    """Yield (private_key, kid, FastAPI test client wired to JWKS provider)."""
    monkeypatch.setenv("SENTRY_DSN", "")
    get_settings.cache_clear()
    private, public = _generate_rsa_keypair()
    kid = "test-key-1"
    provider = _build_jwks_provider(tmp_path, public_key=public, kid=kid)
    app = create_app(auth_provider=provider)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield private, kid, client


@pytest_asyncio.fixture
async def anonymous_app(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[httpx.AsyncClient]:
    """FastAPI test client with NO auth provider configured.

    Used to pin the behaviour of legacy ``X-*-ID`` ingress (works
    without a provider) and of Authorization-bearing requests
    when no provider is configured (must fail-closed with 401
    ``verification_unavailable`` per B5).
    """
    monkeypatch.setenv("SENTRY_DSN", "")
    get_settings.cache_clear()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        yield client


# ─── Anonymous / dependency-level failures ───────────────────────────────


@pytest.mark.asyncio
async def test_get_me_without_authority_returns_401(
    anonymous_app: httpx.AsyncClient,
) -> None:
    response = await anonymous_app.get("/api/v1/auth/me")
    assert response.status_code == 401
    # The handler raises HTTPException; the global handler in
    # main.py wraps it in a ProblemDetails envelope, but the
    # error code we pinned in dependencies.authority lives in
    # the ``detail`` field — assert against the raw response text
    # so the test pins the string a frontend will actually see.
    assert "authority_required" in response.text


@pytest.mark.asyncio
async def test_get_me_with_bearer_but_no_provider_returns_401(
    anonymous_app: httpx.AsyncClient,
) -> None:
    """B5 fail-closed: presenting a Bearer token to an app with
    no provider configured MUST return 401 ``verification_unavailable``
    rather than silently passing through."""
    response = await anonymous_app.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer any.jwt.value"},
    )
    assert response.status_code == 401
    assert "verification_unavailable" in response.text


# ─── Happy path ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_me_with_valid_token_returns_principal(
    keypair_and_app: tuple[rsa.RSAPrivateKey, str, httpx.AsyncClient],
) -> None:
    private, kid, client = keypair_and_app
    token = _sign_rs256(
        private,
        kid=kid,
        claims=_standard_claims(capabilities=["read", "write"]),
    )

    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "principal_id": "auth0|user-123",
        "tenant_id": "tenant-acme",
        "organization_id": "org-1",
        "environment_id": "production",
        "capabilities": ["read", "write"],
        "authority_source": "verified",
    }


@pytest.mark.asyncio
async def test_get_me_capabilities_are_sorted_for_determinism(
    keypair_and_app: tuple[rsa.RSAPrivateKey, str, httpx.AsyncClient],
) -> None:
    """Two requests with the same authority MUST produce byte-equal
    JSON. The capability list is the only collection field, so
    pinning its ordering is what makes byte-equality possible."""
    private, kid, client = keypair_and_app
    token = _sign_rs256(
        private,
        kid=kid,
        claims=_standard_claims(capabilities=["z", "a", "m", "b"]),
    )

    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["capabilities"] == ["a", "b", "m", "z"]


@pytest.mark.asyncio
async def test_get_me_without_tenant_claim_rejected_when_no_platform_scope(
    keypair_and_app: tuple[rsa.RSAPrivateKey, str, httpx.AsyncClient],
) -> None:
    """A verified bearer with no tenant claim and no platform scope
    cannot establish a usable app session."""
    private, kid, client = keypair_and_app
    token = _sign_rs256(
        private,
        kid=kid,
        claims=_standard_claims(tenant_id=None),
    )

    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert "authorized_scope_required" in response.text


@pytest.mark.asyncio
async def test_get_me_platform_admin_without_tenant_claim_still_returns_200(
    keypair_and_app: tuple[rsa.RSAPrivateKey, str, httpx.AsyncClient],
) -> None:
    private, kid, client = keypair_and_app
    token = _sign_rs256(
        private,
        kid=kid,
        claims=_standard_claims(
            tenant_id=None,
            capabilities=["platform.tenant.admin"],
        ),
    )

    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["principal_id"] == "auth0|user-123"
    assert body["tenant_id"] is None
    assert body["capabilities"] == ["platform.tenant.admin"]
    assert body["authority_source"] == "verified"


# ─── Token verification failures ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_me_rejects_wrong_audience(
    keypair_and_app: tuple[rsa.RSAPrivateKey, str, httpx.AsyncClient],
) -> None:
    private, kid, client = keypair_and_app
    token = _sign_rs256(
        private,
        kid=kid,
        claims=_standard_claims(audience="https://attacker.example/api"),
    )
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert "verification_failed" in response.text


@pytest.mark.asyncio
async def test_get_me_rejects_wrong_issuer(
    keypair_and_app: tuple[rsa.RSAPrivateKey, str, httpx.AsyncClient],
) -> None:
    private, kid, client = keypair_and_app
    token = _sign_rs256(
        private,
        kid=kid,
        claims=_standard_claims(issuer="https://attacker.example/"),
    )
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert "verification_failed" in response.text


@pytest.mark.asyncio
async def test_get_me_rejects_expired_token(
    keypair_and_app: tuple[rsa.RSAPrivateKey, str, httpx.AsyncClient],
) -> None:
    private, kid, client = keypair_and_app
    token = _sign_rs256(
        private,
        kid=kid,
        claims=_standard_claims(exp_delta_seconds=-3600),
    )
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert "verification_failed" in response.text


@pytest.mark.asyncio
async def test_get_me_rejects_token_signed_by_unknown_key(
    keypair_and_app: tuple[rsa.RSAPrivateKey, str, httpx.AsyncClient],
) -> None:
    """A token signed by a private key whose public half is NOT in
    the JWKS MUST be rejected — even if every claim is valid."""
    _, kid, client = keypair_and_app
    attacker_private, _ = _generate_rsa_keypair()
    token = _sign_rs256(
        attacker_private, kid=kid, claims=_standard_claims()
    )
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert "verification_failed" in response.text


# ─── Authorization-header parsing failures ───────────────────────────────


@pytest.mark.asyncio
async def test_get_me_rejects_malformed_authorization_header(
    keypair_and_app: tuple[rsa.RSAPrivateKey, str, httpx.AsyncClient],
) -> None:
    _, _, client = keypair_and_app
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "OnlySingleToken"},
    )
    assert response.status_code == 400
    assert "malformed_authorization_header" in response.text


@pytest.mark.asyncio
async def test_get_me_rejects_authorization_plus_legacy_header_conflict(
    keypair_and_app: tuple[rsa.RSAPrivateKey, str, httpx.AsyncClient],
) -> None:
    """Source singularity (Wedge B8 / C2): a request that presents
    both an Authorization header AND an ``X-*-ID`` header is
    structurally ambiguous and MUST be rejected with 400
    ``authority_source_conflict``."""
    private, kid, client = keypair_and_app
    token = _sign_rs256(private, kid=kid, claims=_standard_claims())
    response = await client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Tenant-ID": "tenant-acme",
        },
    )
    assert response.status_code == 400
    assert "authority_source_conflict" in response.text


# ─── Legacy header-attested path ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_me_via_legacy_header_returns_source_header(
    anonymous_app: httpx.AsyncClient,
) -> None:
    """Legacy X-*-ID identity headers are upstream-trusted (the
    network is responsible for stripping them at the edge). The
    middleware accepts them when no Authorization is presented;
    the response advertises ``authority_source = "header"`` so
    auditors can tell verified principals apart from
    header-attested ones at trace time."""
    response = await anonymous_app.get(
        "/api/v1/auth/me",
        headers={
            "X-Tenant-ID": "tenant-acme",
            "X-Principal-ID": "legacy-principal",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["principal_id"] == "legacy-principal"
    assert body["tenant_id"] == "tenant-acme"
    assert body["authority_source"] == "header"
