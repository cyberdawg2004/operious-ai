"""Spec 1b — external coarsening of auth/authority errors (#25)."""

from __future__ import annotations

import json

from app.middleware.auth_error import auth_error_response


def _body(resp) -> dict:  # noqa: ANN001
    return json.loads(bytes(resp.body))


def test_coarse_401_is_generic() -> None:
    resp = auth_error_response(
        status_code=401,
        internal_code="header_authority_disabled",
        reason="legacy headers not accepted",
        coarsen=True,
    )
    assert resp.status_code == 401
    assert _body(resp) == {"error": "unauthorized"}
    assert resp.headers["www-authenticate"] == "Bearer"


def test_coarse_400_is_generic() -> None:
    resp = auth_error_response(
        status_code=400,
        internal_code="malformed_authorization_header",
        reason="bad scheme",
        coarsen=True,
    )
    assert resp.status_code == 400
    assert _body(resp) == {"error": "bad_request"}


def test_detailed_response_when_not_coarsened() -> None:
    resp = auth_error_response(
        status_code=401,
        internal_code="header_authority_disabled",
        reason="legacy headers not accepted",
        coarsen=False,
    )
    body = _body(resp)
    assert body["error"] == "header_authority_disabled"
    assert body["reason"] == "legacy headers not accepted"


def test_403_coarsens_to_forbidden() -> None:
    resp = auth_error_response(
        status_code=403,
        internal_code="insufficient_capability",
        reason="needs tenant.write",
        coarsen=True,
    )
    assert resp.status_code == 403
    assert _body(resp) == {"error": "forbidden"}
    assert "www-authenticate" not in {k.lower() for k in resp.headers}
