"""Spec 1b — rate-limit middlewares are wired into the app pipeline."""

from __future__ import annotations

import os
from unittest.mock import patch

from app.core.config import get_settings
from app.main import create_app


def _names() -> list[str]:
    get_settings.cache_clear()
    try:
        with patch.dict(os.environ, {"ENVIRONMENT": "test", "RATE_LIMIT_ENABLED": "true"}):
            app = create_app()
        return [m.cls.__name__ for m in app.user_middleware]
    finally:
        get_settings.cache_clear()


def test_both_rate_limit_middlewares_registered() -> None:
    names = _names()
    assert "EdgeRateLimitMiddleware" in names
    assert "TenantRateLimitMiddleware" in names


def test_order_edge_outside_authority_tenant_inside() -> None:
    names = _names()
    # user_middleware index 0 == outermost.
    assert names.index("EdgeRateLimitMiddleware") < names.index("AuthorityContextMiddleware")
    assert names.index("AuthorityContextMiddleware") < names.index("TenantRateLimitMiddleware")
