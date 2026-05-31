"""Spec 1b — per-tenant/principal post-auth rate-limit middleware."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.core.rate_limit import RateLimitDecision
from app.middleware.tenant_rate_limit import TenantRateLimitMiddleware


class _Auth:
    def __init__(self, tenant_id: str | None, principal_id: str | None) -> None:
        self.tenant_id = tenant_id
        self.principal_id = principal_id


class _StampAuthority:
    """Pure-ASGI test shim that stamps ``scope['state']['authority']``."""

    def __init__(self, app, authority) -> None:  # noqa: ANN001
        self.app = app
        self.authority = authority

    async def __call__(self, scope, receive, send):  # noqa: ANN001
        if scope["type"] == "http":
            scope["state"] = {"authority": self.authority}
        await self.app(scope, receive, send)


class _Spy:
    def __init__(self, allow_first: int, *, available: bool = True) -> None:
        self.allow_first = allow_first
        self.available = available
        self.calls = 0
        self.keys: list[str] = []

    async def consume(self, *, key, limit, window_seconds) -> RateLimitDecision:  # noqa: ANN001
        self.calls += 1
        self.keys.append(key)
        if not self.available:
            return RateLimitDecision(False, 1, backend_available=False)
        return RateLimitDecision(self.calls <= self.allow_first, 60, backend_available=True)


def _app(limiter, authority, *, principal_per_minute=300):
    async def ok(request):  # noqa: ANN001
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/x", ok)])
    app.add_middleware(
        TenantRateLimitMiddleware,
        limiter=limiter,
        tenant_per_minute=2,
        principal_per_minute=principal_per_minute,
        window_seconds=60,
        enabled=True,
    )
    app.add_middleware(_StampAuthority, authority=authority)
    return app


def test_tenant_key_used_and_blocks() -> None:
    spy = _Spy(allow_first=2)
    client = TestClient(_app(spy, _Auth("t-1", None), principal_per_minute=0))
    assert client.get("/x").status_code == 200
    assert client.get("/x").status_code == 200
    assert client.get("/x").status_code == 429
    assert any(k.startswith("rl:tenant:t-1") for k in spy.keys)


def test_principal_layer_also_checked() -> None:
    spy = _Spy(allow_first=100)
    client = TestClient(_app(spy, _Auth("t-1", "p-1")))
    client.get("/x")
    assert any(k.startswith("rl:tenant:t-1") for k in spy.keys)
    assert any(k.startswith("rl:principal:p-1") for k in spy.keys)


def test_anonymous_request_skips_tenant_layer() -> None:
    spy = _Spy(allow_first=0)
    client = TestClient(_app(spy, _Auth(None, None)))
    assert client.get("/x").status_code == 200
    assert spy.calls == 0


def test_backend_down_get_degrades_open() -> None:
    spy = _Spy(allow_first=0, available=False)
    client = TestClient(_app(spy, _Auth("t-1", None), principal_per_minute=0))
    assert client.get("/x").status_code == 200
