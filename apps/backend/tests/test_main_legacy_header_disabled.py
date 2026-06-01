"""Composition-root wiring for fail-closed header authority (S-01).

The strongest end-to-end statement of the S-01 fix: in a production
build, a legacy ``X-Tenant-ID`` identity header is rejected EVEN when
it arrives from a trusted upstream proxy. Header authority is not an
accepted source in production; only verified bearer credentials are.
"""

from __future__ import annotations

import os
from ipaddress import ip_network
from unittest.mock import patch

from starlette.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app
from app.middleware.authority_context import TENANT_HEADER

_LOCALHOST = (ip_network("127.0.0.0/8"),)
_TRUSTED_CLIENT = ("127.0.0.1", 12345)


def test_production_rejects_legacy_tenant_header_from_trusted_peer() -> None:
    get_settings.cache_clear()
    try:
        with patch.dict(
            os.environ,
            {
                "ENVIRONMENT": "production",
                # Pin header-authority posture, not provider readiness.
                "PRODUCTION_READINESS_ENFORCED": "false",
            },
        ):
            app = create_app(trusted_proxies=_LOCALHOST)
            client = TestClient(
                app,
                client=_TRUSTED_CLIENT,
                raise_server_exceptions=False,
            )
            response = client.get(
                "/healthz", headers={TENANT_HEADER: "victim-tenant"}
            )
        assert response.status_code == 401
        # Production coarsens the external auth error (#25); the precise
        # `header_authority_disabled` code is logged server-side only.
        assert response.json()["error"] == "unauthorized"
    finally:
        get_settings.cache_clear()


def test_non_production_still_honours_legacy_tenant_header() -> None:
    get_settings.cache_clear()
    try:
        with patch.dict(os.environ, {"ENVIRONMENT": "staging"}):
            app = create_app(trusted_proxies=_LOCALHOST)
            client = TestClient(
                app,
                client=_TRUSTED_CLIENT,
                raise_server_exceptions=False,
            )
            response = client.get(
                "/healthz", headers={TENANT_HEADER: "tenant-a"}
            )
        # Not a header-authority rejection (route may 200/404, but the
        # authority middleware did not fail-close).
        assert response.status_code != 401 or (
            response.json().get("error") != "header_authority_disabled"
        )
    finally:
        get_settings.cache_clear()
