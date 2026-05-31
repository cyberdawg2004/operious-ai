"""2.5-I: ``main.create_app`` hardening invariants.

Pinned properties:

* ProblemDetails-shaped HTTPException handler returns RFC 9457 wire
  format with the ``application/problem+json`` media type,
* validation errors emit the same envelope at HTTP 422,
* unhandled exceptions emit a generic ``internal_error`` envelope
  at HTTP 500 (no internal traceback / exception text leaks),
* a wildcard ``CORS_ALLOW_ORIGINS`` setting is rejected at
  composition time,
* production deployments without ``trusted_proxies`` are rejected
  at composition time.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi import APIRouter, HTTPException
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_app
from app.survivability import PROBLEM_DETAILS_MEDIA_TYPE


def _client_with_router(router: APIRouter) -> TestClient:
    """Build an app, mount ``router`` on it, and return a TestClient."""
    app = create_app()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


# ─── Exception handler: HTTPException ────────────────────────────────


def test_http_exception_returns_problem_details() -> None:
    router = APIRouter()

    @router.get("/_test/teapot")
    async def _teapot() -> None:
        raise HTTPException(status_code=418, detail="i_am_a_teapot")

    client = _client_with_router(router)
    response = client.get("/_test/teapot")
    assert response.status_code == 418
    assert response.headers["content-type"].startswith(
        PROBLEM_DETAILS_MEDIA_TYPE
    )
    body = response.json()
    assert body["status"] == 418
    assert body["title"] == "i_am_a_teapot"
    assert body["type"] == "about:blank"


# ─── Exception handler: validation ───────────────────────────────────


def test_validation_error_returns_problem_details() -> None:
    from pydantic import BaseModel

    router = APIRouter()

    class _Body(BaseModel):
        x: int

    @router.post("/_test/validate")
    async def _validate(body: _Body) -> dict[str, int]:
        return {"x": body.x}

    client = _client_with_router(router)
    response = client.post("/_test/validate", json={"x": "not an int"})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith(
        PROBLEM_DETAILS_MEDIA_TYPE
    )
    body = response.json()
    assert body["status"] == 422
    assert body["title"] == "validation_error"
    assert "errors" in body  # extension member


# ─── Exception handler: unhandled ────────────────────────────────────


def test_unhandled_exception_returns_generic_problem_details() -> None:
    router = APIRouter()

    @router.get("/_test/boom")
    async def _boom() -> None:
        raise RuntimeError("internal-secret-detail")

    client = _client_with_router(router)
    response = client.get("/_test/boom")
    assert response.status_code == 500
    assert response.headers["content-type"].startswith(
        PROBLEM_DETAILS_MEDIA_TYPE
    )
    body = response.json()
    assert body["status"] == 500
    assert body["title"] == "internal_error"
    # The internal exception text MUST NOT leak.
    assert "internal-secret-detail" not in str(body)


# ─── CORS posture ────────────────────────────────────────────────────


def test_wildcard_cors_origin_rejected_at_composition() -> None:
    get_settings.cache_clear()
    with patch.dict(os.environ, {"CORS_ALLOW_ORIGINS": "*"}):
        with pytest.raises(ValueError):
            create_app()
    get_settings.cache_clear()


# ─── Production posture ──────────────────────────────────────────────


def test_production_requires_explicit_trusted_proxies(monkeypatch) -> None:
    """A production deployment that forgets to pin
    ``trusted_proxies`` MUST be rejected at composition time."""
    get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "production")
    try:
        with pytest.raises(RuntimeError):
            create_app()
    finally:
        get_settings.cache_clear()


def test_production_with_explicit_empty_proxies_boots() -> None:
    """Empty tuple is the strict fail-closed setting and MUST boot."""
    get_settings.cache_clear()
    with patch.dict(
        os.environ,
        {
            "ENVIRONMENT": "production",
            # This test pins trusted-proxy posture, not provider readiness.
            "PRODUCTION_READINESS_ENFORCED": "false",
        },
    ):
        app = create_app(trusted_proxies=())
    get_settings.cache_clear()
    assert app is not None


def test_settings_does_not_leak_authority_header_literals() -> None:
    """Defense-in-depth: the canonical authority headers must come
    from ``AUTHORITY_HEADERS`` only — config / main may not repeat
    them by string. This is a complement to
    ``test_no_other_source_reads_authority_headers`` for the
    composition root.
    """
    s = Settings(CORS_ALLOW_ORIGINS="https://example.com")
    forbidden = (
        "X-Tenant-ID",
        "X-Principal-ID",
        "X-Organization-ID",
        "X-Environment-ID",
    )
    for v in forbidden:
        assert v not in s.CORS_ALLOW_HEADERS
