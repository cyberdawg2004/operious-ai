"""Spec 1b — AuthorityContext error coarsening in production posture (#25)."""

from __future__ import annotations

import json

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.middleware.authority_context import AuthorityContextMiddleware


def _client(*, coarsen: bool) -> TestClient:
    async def ok(request):  # noqa: ANN001
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/x", ok)])
    app.add_middleware(
        AuthorityContextMiddleware,
        auth_provider=None,
        legacy_header_authority_enabled=False,
        coarsen_errors=coarsen,
    )
    return TestClient(app)


def test_disabled_header_authority_coarsened() -> None:
    resp = _client(coarsen=True).get("/x", headers={"X-Tenant-ID": "t-1"})
    assert resp.status_code == 401
    assert json.loads(resp.text) == {"error": "unauthorized"}


def test_disabled_header_authority_detailed_when_not_coarsened() -> None:
    resp = _client(coarsen=False).get("/x", headers={"X-Tenant-ID": "t-1"})
    assert resp.status_code == 401
    assert json.loads(resp.text)["error"] == "header_authority_disabled"


def test_verification_unavailable_coarsened() -> None:
    resp = _client(coarsen=True).get("/x", headers={"Authorization": "Bearer abc"})
    assert resp.status_code == 401
    assert json.loads(resp.text) == {"error": "unauthorized"}
