"""Per-tenant/principal post-auth inbound rate limiting (spec 1b #39).

Runs INSIDE the authority middleware, so the resolved identity is available on
``scope['state']['authority']``. Anonymous requests (no tenant) skip this layer —
they were already throttled per-IP at the edge. Backend loss applies the same
method-derived fail policy as the edge layer.
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


class TenantRateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: _Limiter,
        tenant_per_minute: int,
        principal_per_minute: int,
        window_seconds: int,
        enabled: bool,
        production: bool = False,
    ) -> None:
        self.app = app
        self._limiter = limiter
        self._tenant_per_minute = tenant_per_minute
        self._principal_per_minute = principal_per_minute
        self._window = window_seconds
        self._enabled = enabled
        # See EdgeRateLimitMiddleware: fail-closed only in production (#38).
        self._production = production

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._enabled:
            await self.app(scope, receive, send)
            return
        authority = (scope.get("state") or {}).get("authority")
        tenant_id = getattr(authority, "tenant_id", None)
        if not tenant_id:
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        checks: list[tuple[str, int]] = [
            (f"rl:tenant:{tenant_id}", self._tenant_per_minute)
        ]
        principal_id = getattr(authority, "principal_id", None)
        if principal_id and self._principal_per_minute > 0:
            checks.append((f"rl:principal:{principal_id}", self._principal_per_minute))

        for key, limit in checks:
            decision = await self._limiter.consume(
                key=key, limit=limit, window_seconds=self._window
            )
            if not decision.backend_available:
                if fail_open_allowed(method) or not self._production:
                    logger.warning("rate_limit_backend_unavailable_degraded", extra={"key": key})
                    continue
                logger.warning("rate_limit_backend_unavailable_closed", extra={"key": key})
                await service_unavailable_response()(scope, receive, send)
                return
            if not decision.allowed:
                await too_many_requests_response(
                    retry_after_seconds=decision.retry_after_seconds
                )(scope, receive, send)
                return
        await self.app(scope, receive, send)


__all__ = ["TenantRateLimitMiddleware"]
