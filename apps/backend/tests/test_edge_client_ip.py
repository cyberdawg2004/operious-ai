"""Edge rate-limit client-IP resolution behind the Fly proxy.

On Fly the TCP peer is always the fly-proxy, so keying the edge per-IP limiter
on the peer collapses every client into one bucket. The real client IP is in the
``Fly-Client-IP`` header, which is only trustworthy when the immediate peer is a
trusted proxy. ``resolve_client_ip`` enforces exactly that, and never trusts the
header from an untrusted peer (anti-spoofing).
"""

from __future__ import annotations

from ipaddress import ip_network

from app.core.rate_limit import RateLimitDecision, resolve_client_ip
from app.middleware.edge_rate_limit import EdgeRateLimitMiddleware

_FLY = (ip_network("172.16.0.0/12"),)


def _scope(peer: str, headers: list[tuple[bytes, bytes]] | None = None) -> dict:
    return {"type": "http", "client": (peer, 0), "headers": headers or []}


def test_no_trusted_proxies_returns_peer() -> None:
    assert resolve_client_ip(_scope("203.0.113.7"), ()) == "203.0.113.7"


def test_trusted_peer_uses_fly_client_ip() -> None:
    scope = _scope("172.19.0.5", [(b"fly-client-ip", b"203.0.113.9")])
    assert resolve_client_ip(scope, _FLY) == "203.0.113.9"


def test_untrusted_peer_ignores_spoofed_header() -> None:
    # Peer is NOT a trusted proxy -> the header is attacker-controlled; ignore it.
    scope = _scope("203.0.113.7", [(b"fly-client-ip", b"10.0.0.1")])
    assert resolve_client_ip(scope, _FLY) == "203.0.113.7"


def test_trusted_peer_without_header_falls_back_to_peer() -> None:
    assert resolve_client_ip(_scope("172.19.0.5"), _FLY) == "172.19.0.5"


def test_trusted_peer_invalid_header_falls_back_to_peer() -> None:
    scope = _scope("172.19.0.5", [(b"fly-client-ip", b"not-an-ip")])
    assert resolve_client_ip(scope, _FLY) == "172.19.0.5"


class _KeyCapturingLimiter:
    def __init__(self) -> None:
        self.keys: list[str] = []

    async def consume(self, *, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        self.keys.append(key)
        return RateLimitDecision(allowed=True, retry_after_seconds=0, backend_available=True)


async def _drive(mw: EdgeRateLimitMiddleware, scope: dict) -> None:
    async def receive():  # noqa: ANN202
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):  # noqa: ANN001, ANN202
        return None

    await mw(scope, receive, send)


async def test_edge_middleware_keys_per_real_client_behind_proxy() -> None:
    limiter = _KeyCapturingLimiter()

    async def app(scope, receive, send):  # noqa: ANN001, ANN202
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = EdgeRateLimitMiddleware(
        app,
        limiter=limiter,
        limit=100,
        window_seconds=60,
        exempt_suffixes=(),
        enabled=True,
        production=True,
        trusted_proxies=_FLY,
    )
    # Same proxy peer (172.19.0.5), two different real clients -> two buckets.
    for client_ip in ("203.0.113.1", "203.0.113.2"):
        await _drive(
            mw,
            {
                "type": "http",
                "method": "GET",
                "path": "/x",
                "client": ("172.19.0.5", 0),
                "headers": [(b"fly-client-ip", client_ip.encode())],
            },
        )
    assert "rl:ip:203.0.113.1" in limiter.keys
    assert "rl:ip:203.0.113.2" in limiter.keys
