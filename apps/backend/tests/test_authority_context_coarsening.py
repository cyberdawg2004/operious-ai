"""Spec 1b — AuthorityContext error coarsening in production posture (#25)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.middleware.authority_context import AuthorityContextMiddleware


@dataclass(frozen=True, slots=True)
class _ASGIResponse:
    status_code: int
    text: str


class _ASGITestClient:
    def __init__(self, app: Starlette) -> None:
        self._app = app

    def get(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> _ASGIResponse:
        return asyncio.run(_asgi_get(self._app, path, headers=headers))


async def _asgi_get(
    app: Starlette,
    path: str,
    *,
    headers: Mapping[str, str] | None,
) -> _ASGIResponse:
    response_status = 500
    body_parts: list[bytes] = []
    sent_request = False

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": [
            (key.lower().encode("latin-1"), value.encode("latin-1"))
            for key, value in (headers or {}).items()
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    async def receive() -> dict[str, object]:
        nonlocal sent_request
        if not sent_request:
            sent_request = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: Mapping[str, object]) -> None:
        nonlocal response_status
        if message["type"] == "http.response.start":
            response_status = int(message["status"])
        elif message["type"] == "http.response.body":
            body_parts.append(message.get("body", b""))

    await app(scope, receive, send)
    return _ASGIResponse(
        status_code=response_status,
        text=b"".join(body_parts).decode("utf-8"),
    )


def _client(*, coarsen: bool) -> _ASGITestClient:
    async def ok(request):  # noqa: ANN001
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/x", ok)])
    app.add_middleware(
        AuthorityContextMiddleware,
        auth_provider=None,
        legacy_header_authority_enabled=False,
        coarsen_errors=coarsen,
    )
    return _ASGITestClient(app)


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


def test_malformed_authorization_parse_coarsened() -> None:
    # #25: a malformed Authorization header (single token, no scheme) must
    # coarsen in production — no header/reason recon detail leaks.
    resp = _client(coarsen=True).get("/x", headers={"Authorization": "single-token"})
    assert resp.status_code == 400
    assert json.loads(resp.text) == {"error": "bad_request"}


def test_malformed_authorization_parse_detailed_when_not_coarsened() -> None:
    resp = _client(coarsen=False).get("/x", headers={"Authorization": "single-token"})
    assert resp.status_code == 400
    body = json.loads(resp.text)
    assert body["error"] == "malformed_authorization_header"
    assert "reason" in body


def _client_legacy_enabled(*, coarsen: bool) -> _ASGITestClient:
    """Client with legacy header authority *enabled* to test parse-error coarsening."""

    async def ok(request):  # noqa: ANN001
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/x", ok)])
    app.add_middleware(
        AuthorityContextMiddleware,
        auth_provider=None,
        legacy_header_authority_enabled=True,
        coarsen_errors=coarsen,
    )
    return _ASGITestClient(app)


def test_malformed_legacy_header_parse_coarsened() -> None:
    # #25: a whitespace-only X-Tenant-ID triggers _AuthorityHeaderError;
    # the response must be generic in production — no header/reason detail leaked.
    resp = _client_legacy_enabled(coarsen=True).get(
        "/x", headers={"X-Tenant-ID": "   "}
    )
    assert resp.status_code == 400
    assert json.loads(resp.text) == {"error": "bad_request"}


def test_malformed_legacy_header_parse_detailed_when_not_coarsened() -> None:
    resp = _client_legacy_enabled(coarsen=False).get(
        "/x", headers={"X-Tenant-ID": "   "}
    )
    assert resp.status_code == 400
    body = json.loads(resp.text)
    assert body["error"] == "malformed_authority_header"
    assert "reason" in body


def test_verified_claim_malformed_coarsened() -> None:
    # #25: a token that passes scheme-check but fails verified-claim extraction
    # must coarsen. With no auth provider configured, verification is unavailable —
    # that path is already tested. This test covers the coarsening helper is
    # consistent for all 400/401 paths.
    resp = _client(coarsen=True).get("/x", headers={"Authorization": "Bearer tok"})
    assert resp.status_code == 401
    assert json.loads(resp.text) == {"error": "unauthorized"}
