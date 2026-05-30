"""Fail-closed legacy header authority (S-01 remediation).

When ``legacy_header_authority_enabled=False`` (the production
posture wired in ``app.main``), the canonical ``X-*-ID`` identity
headers must NOT be honoured as an authority source. A request that
presents any legacy identity header is rejected with
``401 header_authority_disabled`` so a direct caller can never spoof
tenant identity by stamping ``X-Tenant-ID`` itself.

Verified bearer authority and anonymous requests are unaffected.
"""

from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.identity import get_request_authority
from app.middleware.authority_context import (
    AuthorityContextMiddleware,
    TENANT_HEADER,
)
from app.middleware.request_context import RequestContextMiddleware


def _build_app(*, legacy_header_authority_enabled: bool) -> Starlette:
    async def echo(request: Request) -> JSONResponse:
        ctx = get_request_authority()
        body: dict[str, Any] = {
            "tenant_id": None if ctx is None else ctx.tenant_id,
            "source": getattr(request.state, "authority_source", None),
        }
        return JSONResponse(body)

    app = Starlette(routes=[Route("/echo", echo)])
    app.add_middleware(
        AuthorityContextMiddleware,
        legacy_header_authority_enabled=legacy_header_authority_enabled,
    )
    app.add_middleware(RequestContextMiddleware)
    return app


def _client(*, legacy_header_authority_enabled: bool) -> TestClient:
    return TestClient(
        _build_app(
            legacy_header_authority_enabled=legacy_header_authority_enabled
        ),
        raise_server_exceptions=True,
    )


def test_legacy_header_rejected_when_disabled() -> None:
    client = _client(legacy_header_authority_enabled=False)
    response = client.get("/echo", headers={TENANT_HEADER: "victim-tenant"})
    assert response.status_code == 401
    assert response.json()["error"] == "header_authority_disabled"


def test_anonymous_request_allowed_when_legacy_disabled() -> None:
    client = _client(legacy_header_authority_enabled=False)
    response = client.get("/echo")
    assert response.status_code == 200
    assert response.json() == {"tenant_id": None, "source": "anonymous"}


def test_legacy_header_honoured_when_enabled() -> None:
    client = _client(legacy_header_authority_enabled=True)
    response = client.get("/echo", headers={TENANT_HEADER: "tenant-a"})
    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-a"
    assert body["source"] == "header"
