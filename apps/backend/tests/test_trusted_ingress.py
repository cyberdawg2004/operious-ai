"""``TrustedIngressMiddleware`` regression tests (Wedge C4)."""

from __future__ import annotations

from ipaddress import ip_network
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.middleware.authority_context import (
    AUTHORIZATION_HEADER,
    AuthorityContextMiddleware,
    TENANT_HEADER,
)
from app.middleware.request_context import RequestContextMiddleware
from app.middleware.trusted_ingress import (
    AUTHORITY_BEARING_HEADERS,
    TrustedIngressMiddleware,
)


def _build_app(
    *,
    trusted: tuple[Any, ...] = (),
    register_trust: bool = True,
) -> Starlette:
    async def echo(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/echo", echo)])
    app.add_middleware(AuthorityContextMiddleware)
    if register_trust:
        app.add_middleware(
            TrustedIngressMiddleware,
            trusted_proxies=trusted,
        )
    app.add_middleware(RequestContextMiddleware)
    return app


LOCALHOST = (ip_network("127.0.0.0/8"),)

#: Starlette TestClient defaults to ``client=("testclient", 50000)``
#: whose host is not parseable as an IP, so the trust middleware
#: treats it as ``peer=None`` → always untrusted. Tests must pin
#: a real IP to exercise the "trusted peer" path.
_LOCAL_CLIENT = ("127.0.0.1", 12345)
_REMOTE_CLIENT = ("203.0.113.1", 12345)


# ─── Surface ────────────────────────────────────────────────────────


def test_authority_bearing_headers_pinned() -> None:
    assert AUTHORITY_BEARING_HEADERS == (
        "Authorization",
        "X-Tenant-ID",
        "X-Principal-ID",
        "X-Organization-ID",
        "X-Environment-ID",
    )


# ─── Trust enforcement ─────────────────────────────────────────────


def test_no_claim_passes_through_when_untrusted() -> None:
    """Anonymous request from an untrusted peer is fine — trust
    only matters when authority is claimed."""
    client = TestClient(_build_app(trusted=()), client=_REMOTE_CLIENT)
    resp = client.get("/echo")
    assert resp.status_code == 200


def test_authorization_from_untrusted_peer_rejected() -> None:
    client = TestClient(_build_app(trusted=()), client=_REMOTE_CLIENT)
    resp = client.get(
        "/echo", headers={AUTHORIZATION_HEADER: "Bearer x"}
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "untrusted_ingress"
    assert AUTHORIZATION_HEADER in body["headers"]


def test_xtenant_from_untrusted_peer_rejected() -> None:
    client = TestClient(_build_app(trusted=()), client=_REMOTE_CLIENT)
    resp = client.get("/echo", headers={TENANT_HEADER: "acme"})
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "untrusted_ingress"
    assert TENANT_HEADER in body["headers"]


def test_trusted_peer_passes_through() -> None:
    """Peer in 127.0.0.0/8 → trusted. Downstream
    AuthorityContextMiddleware handles X-*-ID normally."""
    client = TestClient(
        _build_app(trusted=LOCALHOST), client=_LOCAL_CLIENT
    )
    resp = client.get("/echo", headers={TENANT_HEADER: "acme"})
    assert resp.status_code == 200


def test_trusted_peer_authorization_reaches_downstream() -> None:
    """Authorization from a trusted peer is forwarded to
    AuthorityContextMiddleware, which (with no provider configured
    in this app) returns 401 verification_unavailable. The trust
    middleware itself does not block."""
    client = TestClient(
        _build_app(trusted=LOCALHOST), client=_LOCAL_CLIENT
    )
    resp = client.get(
        "/echo", headers={AUTHORIZATION_HEADER: "Bearer x"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"] == "verification_unavailable"


def test_multiple_tainted_headers_listed() -> None:
    client = TestClient(_build_app(trusted=()), client=_REMOTE_CLIENT)
    resp = client.get(
        "/echo",
        headers={
            AUTHORIZATION_HEADER: "Bearer x",
            TENANT_HEADER: "acme",
        },
    )
    assert resp.status_code == 400
    body = resp.json()
    headers = set(body["headers"])
    assert AUTHORIZATION_HEADER in headers
    assert TENANT_HEADER in headers


@pytest.mark.parametrize(
    "header",
    [
        "X-Tenant-ID",
        "X-Principal-ID",
        "X-Organization-ID",
        "X-Environment-ID",
        "Authorization",
    ],
)
def test_every_authority_header_individually_rejected(
    header: str,
) -> None:
    client = TestClient(_build_app(trusted=()), client=_REMOTE_CLIENT)
    resp = client.get("/echo", headers={header: "v"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "untrusted_ingress"


def test_peer_outside_allowlist_rejected() -> None:
    """Allowlist covers a different range than the peer."""
    other = (ip_network("10.0.0.0/8"),)
    client = TestClient(_build_app(trusted=other), client=_REMOTE_CLIENT)
    resp = client.get("/echo", headers={TENANT_HEADER: "acme"})
    assert resp.status_code == 400


def test_unknown_peer_treated_as_untrusted() -> None:
    """A peer whose host is not a parseable IP (e.g., Starlette's
    default ``testclient`` literal) is treated as untrusted."""
    client = TestClient(_build_app(trusted=LOCALHOST))
    resp = client.get("/echo", headers={TENANT_HEADER: "acme"})
    assert resp.status_code == 400
    body = resp.json()
    assert body["peer"] == "unknown"


# ─── Backward compatibility ────────────────────────────────────────


def test_without_trust_middleware_b8_behaviour_intact() -> None:
    """When TrustedIngressMiddleware is not registered, the
    existing B8 ingress works byte-for-byte."""
    client = TestClient(_build_app(register_trust=False))
    resp = client.get("/echo", headers={TENANT_HEADER: "acme"})
    assert resp.status_code == 200


# ─── create_app integration ────────────────────────────────────────


def test_create_app_default_omits_trust_middleware() -> None:
    """Default ``create_app()`` does NOT register the trust
    middleware. B8/C2 legacy + test deployments unaffected."""
    from app.main import create_app

    app = create_app()
    classes = [m.cls for m in app.user_middleware]
    assert TrustedIngressMiddleware not in classes


def test_create_app_trusted_proxies_registers_middleware() -> None:
    from app.main import create_app

    app = create_app(trusted_proxies=LOCALHOST)
    classes = [m.cls for m in app.user_middleware]
    assert TrustedIngressMiddleware in classes


def test_create_app_empty_trusted_proxies_still_registers() -> None:
    """Empty tuple is the STRICT fail-closed setting; the
    middleware must be registered to enforce it."""
    from app.main import create_app

    app = create_app(trusted_proxies=())
    classes = [m.cls for m in app.user_middleware]
    assert TrustedIngressMiddleware in classes


def test_create_app_middleware_order_correct() -> None:
    """Request flow must be:
    RequestContext (outer) → TrustedIngress → AuthorityContext → Router.

    Starlette prepends, so the LAST-registered class sits at
    index 0 (outermost). We therefore want indices to be:
    request_ctx < trusted_ingress < authority_ctx.
    """
    from app.main import create_app

    app = create_app(trusted_proxies=LOCALHOST)
    user_middleware = list(app.user_middleware)
    req_idx = next(
        i
        for i, m in enumerate(user_middleware)
        if m.cls is RequestContextMiddleware
    )
    trust_idx = next(
        i
        for i, m in enumerate(user_middleware)
        if m.cls is TrustedIngressMiddleware
    )
    auth_idx = next(
        i
        for i, m in enumerate(user_middleware)
        if m.cls is AuthorityContextMiddleware
    )
    assert req_idx < trust_idx < auth_idx
