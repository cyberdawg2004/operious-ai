"""Spec 1b — per-IP pre-auth edge rate-limit middleware."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.core.rate_limit import RateLimitDecision
from app.middleware.edge_rate_limit import EdgeRateLimitMiddleware


class _StubLimiter:
    def __init__(self, allow_first: int, *, available: bool = True) -> None:
        self.allow_first = allow_first
        self.available = available
        self.calls = 0
        self.keys: list[str] = []

    async def consume(self, *, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        self.calls += 1
        self.keys.append(key)
        if not self.available:
            return RateLimitDecision(False, 1, backend_available=False)
        return RateLimitDecision(self.calls <= self.allow_first, 60, backend_available=True)


def _app(limiter, *, exempt=()) -> Starlette:
    async def ok(request):  # noqa: ANN001
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/x", ok), Route("/health", ok)])
    app.add_middleware(
        EdgeRateLimitMiddleware,
        limiter=limiter,
        limit=2,
        window_seconds=60,
        exempt_suffixes=exempt,
        enabled=True,
    )
    return app


def test_allows_then_blocks_with_429() -> None:
    limiter = _StubLimiter(allow_first=2)
    client = TestClient(_app(limiter))
    assert client.get("/x").status_code == 200
    assert client.get("/x").status_code == 200
    blocked = client.get("/x")
    assert blocked.status_code == 429
    assert "retry-after" in {k.lower() for k in blocked.headers}
    assert all(k.startswith("rl:ip:") for k in limiter.keys)


def test_health_path_exempt() -> None:
    limiter = _StubLimiter(allow_first=0)
    client = TestClient(_app(limiter, exempt=("/health",)))
    assert client.get("/health").status_code == 200
    assert limiter.calls == 0  # never consulted the limiter


def test_redis_down_get_fails_open() -> None:
    client = TestClient(_app(_StubLimiter(allow_first=0, available=False)))
    assert client.get("/x").status_code == 200  # GET degrades open


def test_redis_down_post_fails_closed_503() -> None:
    async def ok(request):  # noqa: ANN001
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/x", ok, methods=["POST"])])
    app.add_middleware(
        EdgeRateLimitMiddleware,
        limiter=_StubLimiter(allow_first=0, available=False),
        limit=2,
        window_seconds=60,
        exempt_suffixes=(),
        enabled=True,
    )
    assert TestClient(app).post("/x").status_code == 503


def test_disabled_passes_through() -> None:
    limiter = _StubLimiter(allow_first=0)
    async def ok(request):  # noqa: ANN001
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/x", ok)])
    app.add_middleware(
        EdgeRateLimitMiddleware,
        limiter=limiter,
        limit=2,
        window_seconds=60,
        exempt_suffixes=(),
        enabled=False,
    )
    assert TestClient(app).get("/x").status_code == 200
    assert limiter.calls == 0
