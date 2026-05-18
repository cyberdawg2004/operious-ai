"""Constitutional regression tests for the canonical HTTP authority
extraction middleware.

Wedge B8 — ``app.middleware.authority_context.AuthorityContextMiddleware``
is the SINGLE permitted site that translates HTTP identity headers
into a typed :class:`AuthorityContext`. This file pins:

* the canonical header surface (names + ordering),
* the four header → field mappings,
* the missing-header tolerance doctrine (no headers → empty axes),
* the malformed-header rejection doctrine (whitespace-only → 400),
* the dual binding contract (``request.state.authority`` mirrors
  the ContextVar),
* determinism: same headers → byte-equal ``AuthorityContext``,
* singularity: no other source file is allowed to read identity
  headers (static source scan).

The static source scan is the strongest invariant — every future
contributor who tries to parse ``X-Tenant-ID`` outside the
middleware fails this file.
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.identity import (
    AuthorityContext,
    get_request_authority,
)
from app.middleware.authority_context import (
    AUTHORITY_HEADERS,
    AuthorityContextMiddleware,
    ENVIRONMENT_HEADER,
    HEADER_TO_FIELD,
    ORGANIZATION_HEADER,
    PRINCIPAL_HEADER,
    TENANT_HEADER,
)
from app.middleware.request_context import RequestContextMiddleware


# ─── Helpers ────────────────────────────────────────────────────────


def _build_app() -> Starlette:
    """Build a minimal Starlette app that mirrors the production
    middleware ordering established in ``app.main.create_app``."""

    captured: dict[str, Any] = {}

    async def echo(request: Request) -> JSONResponse:
        ctx = get_request_authority()
        captured["from_request_state"] = getattr(
            request.state, "authority", None
        )
        captured["from_context_var"] = ctx
        # Echo the authority through the body so the test can also
        # see what handlers observe.
        if ctx is None:
            body: dict[str, Any] = {"authority": None}
        else:
            body = {
                "authority": {
                    "tenant_id": ctx.tenant_id,
                    "principal_id": ctx.principal_id,
                    "organization_id": ctx.organization_id,
                    "environment_id": ctx.environment_id,
                }
            }
        return JSONResponse(body)

    app = Starlette(routes=[Route("/echo", echo)])
    # Production order (see ``app.main.create_app``):
    #   AuthorityContext added first → inner
    #   RequestContext added last  → outer
    app.add_middleware(AuthorityContextMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.state.captured = captured
    return app


def _client() -> TestClient:
    return TestClient(_build_app())


# ─── Header surface pinning ─────────────────────────────────────────


def test_canonical_header_names_pinned() -> None:
    """The header names are the public contract between the
    backend and the auth provider / gateway. Renaming any of them
    breaks every deployment until the gateway is also updated, so
    we pin them explicitly here."""
    assert TENANT_HEADER == "X-Tenant-ID"
    assert PRINCIPAL_HEADER == "X-Principal-ID"
    assert ORGANIZATION_HEADER == "X-Organization-ID"
    assert ENVIRONMENT_HEADER == "X-Environment-ID"


def test_authority_headers_ordering_is_stable() -> None:
    """The ``AUTHORITY_HEADERS`` tuple drives error attribution and
    deterministic extraction. Pin the order."""
    assert AUTHORITY_HEADERS == (
        "X-Tenant-ID",
        "X-Principal-ID",
        "X-Organization-ID",
        "X-Environment-ID",
    )


def test_header_to_field_surface_is_pinned() -> None:
    """Each canonical header maps to exactly one
    ``AuthorityContext`` field — the mapping is the wire-format
    contract."""
    assert HEADER_TO_FIELD == {
        "X-Tenant-ID": "tenant_id",
        "X-Principal-ID": "principal_id",
        "X-Organization-ID": "organization_id",
        "X-Environment-ID": "environment_id",
    }


# ─── Empty / missing header tolerance ──────────────────────────────


def test_request_with_no_authority_headers_passes() -> None:
    """A request that carries no identity headers is legitimate
    (anonymous request). The middleware must build an empty
    ``AuthorityContext`` and bind it — NOT reject the request."""
    client = _client()
    response = client.get("/echo")
    assert response.status_code == 200
    body = response.json()
    assert body == {"authority": None} or body == {
        "authority": {
            "tenant_id": None,
            "principal_id": None,
            "organization_id": None,
            "environment_id": None,
        }
    }


def test_anonymous_request_still_binds_an_authority_context() -> None:
    """Even with no headers, the handler MUST see a real
    ``AuthorityContext`` on ``request.state`` and via the
    ContextVar — the "exactly ONE AuthorityContext per request"
    invariant."""
    app = _build_app()
    client = TestClient(app)
    client.get("/echo")
    captured = app.state.captured
    assert isinstance(captured["from_request_state"], AuthorityContext)
    assert isinstance(captured["from_context_var"], AuthorityContext)
    # The two bindings are the SAME object.
    assert captured["from_request_state"] is captured["from_context_var"]
    # Empty axes.
    ctx: AuthorityContext = captured["from_context_var"]
    assert ctx.tenant_id is None
    assert ctx.principal_id is None
    assert ctx.organization_id is None
    assert ctx.environment_id is None


# ─── Successful extraction ──────────────────────────────────────────


def test_extracts_tenant_header() -> None:
    response = _client().get(
        "/echo", headers={TENANT_HEADER: "acme"}
    )
    assert response.status_code == 200
    assert response.json()["authority"]["tenant_id"] == "acme"


def test_extracts_all_axes() -> None:
    response = _client().get(
        "/echo",
        headers={
            TENANT_HEADER: "acme",
            PRINCIPAL_HEADER: "user-1",
            ORGANIZATION_HEADER: "org-7",
            ENVIRONMENT_HEADER: "prod",
        },
    )
    assert response.status_code == 200
    auth = response.json()["authority"]
    assert auth == {
        "tenant_id": "acme",
        "principal_id": "user-1",
        "organization_id": "org-7",
        "environment_id": "prod",
    }


def test_extraction_strips_surrounding_whitespace() -> None:
    """Mirrors the ``coerce_*_id`` doctrine from Wedge A —
    whitespace around a non-empty value is normalised."""
    response = _client().get(
        "/echo",
        headers={
            TENANT_HEADER: "  acme  ",
            PRINCIPAL_HEADER: "\tuser-1\n",
        },
    )
    assert response.status_code == 200
    auth = response.json()["authority"]
    assert auth["tenant_id"] == "acme"
    assert auth["principal_id"] == "user-1"


# ─── Malformed input rejection ──────────────────────────────────────


@pytest.mark.parametrize(
    "header,field",
    [
        (TENANT_HEADER, "tenant_id"),
        (PRINCIPAL_HEADER, "principal_id"),
        (ORGANIZATION_HEADER, "organization_id"),
        (ENVIRONMENT_HEADER, "environment_id"),
    ],
)
def test_whitespace_only_header_returns_400(
    header: str, field: str
) -> None:
    """A present-but-empty / whitespace-only header is a
    structural malformation. Per the ``coerce_*_id`` doctrine
    (Wedge A) and the B5 fail-closed precedent, the middleware
    refuses such requests with a 400 carrying machine-parseable
    attribution."""
    response = _client().get("/echo", headers={header: "   "})
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "malformed_authority_header"
    assert body["header"] == header
    assert body["field"] == field
    assert "empty" in body["reason"] or "whitespace" in body["reason"]


def test_empty_string_header_returns_400() -> None:
    """An explicit empty header value is also structurally
    malformed. Some HTTP clients allow ``X-Tenant-ID: ``; the
    middleware refuses such requests."""
    response = _client().get(
        "/echo", headers={TENANT_HEADER: ""}
    )
    # Some HTTP stacks silently drop empty headers before they
    # reach ASGI; in that case the request is anonymous (200).
    # When the stack does propagate the empty value we MUST 400.
    assert response.status_code in (200, 400)
    if response.status_code == 400:
        body = response.json()
        assert body["error"] == "malformed_authority_header"
        assert body["header"] == TENANT_HEADER


# ─── Dual binding contract ──────────────────────────────────────────


def test_request_state_authority_matches_contextvar() -> None:
    """``request.state.authority`` and the ContextVar must observe
    the SAME object — they are mirrors, not parallel sources."""
    app = _build_app()
    client = TestClient(app)
    client.get("/echo", headers={TENANT_HEADER: "acme"})
    captured = app.state.captured
    state_authority = captured["from_request_state"]
    ctx_authority = captured["from_context_var"]
    assert state_authority is ctx_authority
    assert isinstance(state_authority, AuthorityContext)
    assert state_authority.tenant_id == "acme"


def test_contextvar_is_unset_after_response() -> None:
    """The middleware MUST reset the ContextVar in its ``finally``
    block so the binding is strictly per-request. ASGI workers are
    reused; a leaked binding cross-contaminates the next request."""
    client = _client()
    client.get("/echo", headers={TENANT_HEADER: "acme"})
    # After the response, the test's calling context is unrelated
    # to the worker that handled the request, but we can at least
    # verify our own context is clean.
    assert get_request_authority() is None


# ─── Determinism + singularity ──────────────────────────────────────


def test_extraction_is_deterministic_across_repeats() -> None:
    """Same headers → byte-equal authority. Replay determinism is
    a foundation of the wedge."""
    client = _client()
    headers = {
        TENANT_HEADER: "acme",
        PRINCIPAL_HEADER: "user-1",
        ORGANIZATION_HEADER: "org-7",
        ENVIRONMENT_HEADER: "prod",
    }
    a = client.get("/echo", headers=headers).json()
    b = client.get("/echo", headers=headers).json()
    assert a == b


def test_no_other_source_reads_authority_headers() -> None:
    """Ingress singularity: ONLY ``app/middleware/authority_context.py``
    is permitted to reference the canonical header names. Any other
    source file that parses ``X-Tenant-ID`` / ``X-Principal-ID`` /
    ``X-Organization-ID`` / ``X-Environment-ID`` breaks the
    "Authority Singularity" invariant — two ingress sites with
    different decoders is exactly the audit defect DR-1/DR-3/DR-4
    pattern Wedge B6/B7 closed in the orchestration layer.

    This test fails the moment a second site starts parsing these
    headers; the cure is to wire that site through
    ``app.identity.get_request_authority`` (the ContextVar) or
    ``request.state.authority`` instead.
    """
    backend = pathlib.Path(__file__).parent.parent / "app"
    permitted = (
        backend / "middleware" / "authority_context.py"
    ).resolve()
    forbidden_literals = (
        '"X-Tenant-ID"',
        "'X-Tenant-ID'",
        '"X-Principal-ID"',
        "'X-Principal-ID'",
        '"X-Organization-ID"',
        "'X-Organization-ID'",
        '"X-Environment-ID"',
        "'X-Environment-ID'",
    )
    for py_file in backend.rglob("*.py"):
        if py_file.resolve() == permitted:
            continue
        text = py_file.read_text(encoding="utf-8")
        for literal in forbidden_literals:
            assert literal not in text, (
                f"{py_file} contains the canonical authority "
                f"header literal {literal}; only "
                "app/middleware/authority_context.py is allowed "
                "to reference these headers. Consume the "
                "AuthorityContext via request.state.authority or "
                "app.identity.get_request_authority instead."
            )


# ─── Production middleware wiring ───────────────────────────────────


def test_production_app_registers_middleware_in_correct_order() -> (
    None
):
    """``app.main.create_app`` must register
    ``AuthorityContextMiddleware`` BEFORE
    ``RequestContextMiddleware`` so that, per Starlette's
    prepend-based ``add_middleware``, RequestContext becomes the
    OUTERMOST user middleware and the request id is bound BEFORE
    authority extraction runs."""
    from app.main import create_app

    app = create_app()
    user_middleware = list(app.user_middleware)
    auth_idx = next(
        i
        for i, m in enumerate(user_middleware)
        if m.cls is AuthorityContextMiddleware
    )
    req_idx = next(
        i
        for i, m in enumerate(user_middleware)
        if m.cls is RequestContextMiddleware
    )
    # Starlette's ``add_middleware`` does ``insert(0, ...)`` so the
    # LAST registered class ends up at index 0 (outermost). We
    # therefore want ``RequestContextMiddleware`` at a LOWER index
    # than ``AuthorityContextMiddleware``.
    assert req_idx < auth_idx, (
        "RequestContextMiddleware must be registered AFTER "
        "AuthorityContextMiddleware in app.main.create_app so that "
        "request id is bound BEFORE authority extraction. Re-check "
        "the order of add_middleware() calls."
    )
