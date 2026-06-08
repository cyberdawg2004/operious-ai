"""Constitutional regression tests for Wedge C2 — auth-provider /
middleware integration.

Pins:

* Authorization parsing surface (header constant, malformed → 400).
* Source singularity: Authorization + X-*-ID together → 400.
* Provider verification success → source = "verified",
  AuthorityContext from VerifiedIdentity.
* Provider verification failure → 401 verification_failed.
* No provider configured + Authorization → 401 verification_unavailable
  (B5 fail-closed).
* Provider returning malformed claim → 400 malformed_verified_claim.
* Source attribution constants pinned; ``request.state.authority_source``
  set for every successful path.
* B8 invariants intact when no provider configured: anonymous +
  X-*-ID paths byte-identical to pre-C2.
* ``create_app(auth_provider=...)`` plumbs provider through.
"""

from __future__ import annotations

from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.auth import (
    AuthenticationError,
    AuthProvider,
    Credential,
    VerifiedIdentity,
)
from app.identity import AuthorityContext
from app.middleware.authority_context import (
    AUTHORITY_SOURCE_ANONYMOUS,
    AUTHORITY_SOURCE_HEADER,
    AUTHORITY_SOURCE_VERIFIED,
    AUTHORITY_SOURCES,
    AUTHORIZATION_HEADER,
    AuthorityContextMiddleware,
    TENANT_HEADER,
)
from app.middleware.request_context import RequestContextMiddleware


# ─── Test provider fixtures ─────────────────────────────────────────


class _SuccessProvider:
    name: str = "test_success"

    def __init__(self, identity: VerifiedIdentity) -> None:
        self._identity = identity
        self.calls: list[Credential] = []

    async def verify(self, credential: Credential) -> VerifiedIdentity:
        self.calls.append(credential)
        return self._identity


class _RejectProvider:
    name: str = "test_reject"

    def __init__(self, message: str = "rejected") -> None:
        self._message = message

    async def verify(self, credential: Credential) -> VerifiedIdentity:
        raise AuthenticationError(self._message)


# ─── App factory ────────────────────────────────────────────────────


def _build_app(*, auth_provider: AuthProvider | None = None) -> Starlette:
    captured: dict[str, Any] = {}

    async def echo(request: Request) -> JSONResponse:
        captured["authority"] = getattr(
            request.state, "authority", None
        )
        captured["authority_source"] = getattr(
            request.state, "authority_source", None
        )
        ctx = getattr(request.state, "authority", None)
        return JSONResponse(
            {
                "source": getattr(
                    request.state, "authority_source", None
                ),
                "tenant_id": ctx.tenant_id if ctx else None,
                "principal_id": ctx.principal_id if ctx else None,
            }
        )

    app = Starlette(routes=[Route("/echo", echo)])
    app.add_middleware(
        AuthorityContextMiddleware,
        auth_provider=auth_provider,
    )
    app.add_middleware(RequestContextMiddleware)
    app.state.captured = captured
    return app


# ─── Source attribution constants ───────────────────────────────────


def test_source_constants_pinned() -> None:
    assert AUTHORITY_SOURCE_VERIFIED == "verified"
    assert AUTHORITY_SOURCE_HEADER == "header"
    assert AUTHORITY_SOURCE_ANONYMOUS == "anonymous"
    assert AUTHORITY_SOURCES == (
        "verified",
        "header",
        "anonymous",
    )


def test_authorization_header_constant_pinned() -> None:
    assert AUTHORIZATION_HEADER == "Authorization"


# ─── B8 invariants preserved with no provider ──────────────────────


def test_no_provider_anonymous_request_marks_source_anonymous() -> (
    None
):
    app = _build_app(auth_provider=None)
    client = TestClient(app)
    resp = client.get("/echo")
    assert resp.status_code == 200
    assert resp.json()["source"] == "anonymous"
    assert isinstance(
        app.state.captured["authority"], AuthorityContext
    )
    assert app.state.captured["authority"].tenant_id is None


def test_no_provider_legacy_header_marks_source_header() -> None:
    app = _build_app(auth_provider=None)
    client = TestClient(app)
    resp = client.get("/echo", headers={TENANT_HEADER: "acme"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "header"
    assert body["tenant_id"] == "acme"


def test_no_provider_authorization_returns_verification_unavailable() -> (
    None
):
    """Wedge C2 / B5 fail-closed: presenting a credential to an
    unconfigured ingress must NOT silently fall through to
    anonymous — 401."""
    app = _build_app(auth_provider=None)
    client = TestClient(app)
    resp = client.get(
        "/echo",
        headers={AUTHORIZATION_HEADER: "Bearer abc"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"] == "verification_unavailable"


# ─── Provider verification success ──────────────────────────────────


def test_provider_success_yields_verified_authority() -> None:
    identity = VerifiedIdentity(
        tenant_id="acme",
        principal_id="user-1",
        issuer="test_success",
    )
    provider = _SuccessProvider(identity)
    app = _build_app(auth_provider=provider)
    client = TestClient(app)
    resp = client.get(
        "/echo",
        headers={AUTHORIZATION_HEADER: "Bearer abc"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "verified"
    assert body["tenant_id"] == "acme"
    assert body["principal_id"] == "user-1"
    # Provider was invoked with the parsed credential.
    assert len(provider.calls) == 1
    assert provider.calls[0] == Credential(
        scheme="Bearer", value="abc"
    )


def test_provider_success_binds_request_state() -> None:
    identity = VerifiedIdentity(tenant_id="acme", issuer="t")
    app = _build_app(auth_provider=_SuccessProvider(identity))
    client = TestClient(app)
    client.get(
        "/echo", headers={AUTHORIZATION_HEADER: "Bearer x"}
    )
    captured = app.state.captured
    assert captured["authority_source"] == "verified"
    assert isinstance(captured["authority"], AuthorityContext)
    assert captured["authority"].tenant_id == "acme"


# ─── Provider verification failure ──────────────────────────────────


def test_provider_rejection_returns_verification_failed() -> None:
    provider = _RejectProvider(message="bad signature")
    app = _build_app(auth_provider=provider)
    client = TestClient(app)
    resp = client.get(
        "/echo", headers={AUTHORIZATION_HEADER: "Bearer x"}
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"] == "verification_failed"
    assert body["reason"] == "bad signature"


# ─── Malformed verified claim ───────────────────────────────────────


def test_provider_returning_malformed_claim_returns_400() -> None:
    """Provider attested a structurally malformed identity
    (whitespace-only tenant). Substrate doesn't swallow."""
    identity = VerifiedIdentity(tenant_id="   ", issuer="t")
    app = _build_app(auth_provider=_SuccessProvider(identity))
    client = TestClient(app)
    resp = client.get(
        "/echo", headers={AUTHORIZATION_HEADER: "Bearer x"}
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "malformed_verified_claim"


# ─── Authorization parse errors ─────────────────────────────────────


@pytest.mark.parametrize(
    "value,description",
    [
        ("   ", "whitespace-only"),
        ("Bearer", "single-token"),
        ("Bearer ", "missing value after scheme"),
    ],
)
def test_malformed_authorization_returns_400(
    value: str, description: str
) -> None:
    app = _build_app(auth_provider=_SuccessProvider(VerifiedIdentity()))
    client = TestClient(app)
    resp = client.get(
        "/echo", headers={AUTHORIZATION_HEADER: value}
    )
    assert resp.status_code == 400, description
    body = resp.json()
    assert body["error"] == "malformed_authorization_header"
    # #25: the header name is folded into ``reason`` (coarsened away in prod).
    assert AUTHORIZATION_HEADER in body["reason"]


# ─── Source singularity ─────────────────────────────────────────────


def test_authorization_and_xtenant_returns_conflict() -> None:
    """The same constitutional class as DR-3/DR-4: two authority
    sources on one request are ambiguous → 400."""
    provider = _SuccessProvider(VerifiedIdentity(tenant_id="acme"))
    app = _build_app(auth_provider=provider)
    client = TestClient(app)
    resp = client.get(
        "/echo",
        headers={
            AUTHORIZATION_HEADER: "Bearer x",
            TENANT_HEADER: "acme",
        },
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "authority_source_conflict"
    # Provider was NOT invoked — singularity check is upstream.
    assert provider.calls == []


def test_conflict_also_fires_without_provider_configured() -> None:
    """The conflict is structural — independent of whether a
    provider is wired."""
    app = _build_app(auth_provider=None)
    client = TestClient(app)
    resp = client.get(
        "/echo",
        headers={
            AUTHORIZATION_HEADER: "Bearer x",
            TENANT_HEADER: "acme",
        },
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "authority_source_conflict"


# ─── Determinism (verified path) ────────────────────────────────────


def test_verified_extraction_deterministic_across_repeats() -> None:
    identity = VerifiedIdentity(
        tenant_id="acme",
        principal_id="user-1",
        organization_id="org-7",
        environment_id="prod",
    )
    provider = _SuccessProvider(identity)
    client = TestClient(_build_app(auth_provider=provider))
    headers = {AUTHORIZATION_HEADER: "Bearer abc"}
    a = client.get("/echo", headers=headers).json()
    b = client.get("/echo", headers=headers).json()
    assert a == b
    assert len(provider.calls) == 2  # invoked per-request


# ─── create_app integration ─────────────────────────────────────────


def test_create_app_default_has_no_provider() -> None:
    """Default ``create_app()`` ships with no provider — preserves
    B8 byte-for-byte and forces explicit opt-in for verification."""
    from app.main import create_app

    app = create_app()
    middleware = next(
        m
        for m in app.user_middleware
        if m.cls is AuthorityContextMiddleware
    )
    assert middleware.kwargs.get("auth_provider") is None


def test_create_app_threads_provider_through() -> None:
    from app.main import create_app

    provider = _SuccessProvider(VerifiedIdentity(tenant_id="acme"))
    app = create_app(auth_provider=provider)
    middleware = next(
        m
        for m in app.user_middleware
        if m.cls is AuthorityContextMiddleware
    )
    assert middleware.kwargs.get("auth_provider") is provider
