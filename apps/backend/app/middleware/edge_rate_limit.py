"""Per-IP pre-auth inbound rate limiting (spec 1b #39).

Runs OUTSIDE the authority middleware so a flood of unauthenticated requests is
throttled before any auth work is done. Keyed by the connecting peer IP. On
backend loss the method-derived fail policy applies (reads degrade open, writes
fail closed) — never a silent fail-open.
"""

from __future__ import annotations

import logging
from typing import Protocol

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.rate_limit import (
    RateLimitDecision,
    fail_open_allowed,
    service_unavailable_response,
    too_many_requests_response,
)

logger = logging.getLogger(__name__)


class _Limiter(Protocol):
    async def consume(
        self, *, key: str, limit: int, window_seconds: int
    ) -> RateLimitDecision: ...


class EdgeRateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: _Limiter,
        limit: int,
        window_seconds: int,
        exempt_suffixes: tuple[str, ...],
        enabled: bool,
        production: bool = False,
    ) -> None:
        self.app = app
        self._limiter = limiter
        self._limit = limit
        self._window = window_seconds
        self._exempt = tuple(exempt_suffixes)
        self._enabled = enabled
        # Fail-closed on backend loss is a PRODUCTION security stance (#38);
        # outside production a Redis outage degrades open so dev / CI without
        # Redis is not 503'd on every write.
        self._production = production

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._enabled:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if any(path.endswith(suffix) for suffix in self._exempt):
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "GET")
        ip = _client_ip(scope)
        decision = await self._limiter.consume(
            key=f"rl:ip:{ip}", limit=self._limit, window_seconds=self._window
        )
        if not decision.backend_available:
            if fail_open_allowed(method) or not self._production:
                logger.warning("rate_limit_backend_unavailable_degraded", extra={"ip": ip})
                await self.app(scope, receive, send)
                return
            logger.warning("rate_limit_backend_unavailable_closed", extra={"ip": ip})
            await service_unavailable_response()(scope, receive, send)
            return
        if not decision.allowed:
            await too_many_requests_response(
                retry_after_seconds=decision.retry_after_seconds
            )(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _client_ip(scope: Scope) -> str:
    client = scope.get("client")
    if client:
        return str(client[0])
    return "unknown"


__all__ = ["EdgeRateLimitMiddleware"]
