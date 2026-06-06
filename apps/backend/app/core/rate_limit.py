"""Fixed-window inbound rate-limit primitive (spec 1b #39).

A single atomic Redis script increments the per-IP / tenant / principal request
counter and ensures the key always has an expiry. Fixed-window is intentionally
chosen over a token bucket: it needs no local state and is exact enough for
inbound abuse control. Any Redis error yields a ``backend_available=False``
decision so callers can apply a fail-closed / fail-degraded policy explicitly —
the limiter never silently allows on backend failure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final, Protocol

from starlette.responses import Response

from app.survivability import PROBLEM_DETAILS_MEDIA_TYPE

_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_INCREMENT_AND_BOUND_WINDOW_SCRIPT: Final[str] = """
local count = redis.call("INCR", KEYS[1])
local ttl = redis.call("TTL", KEYS[1])
if ttl < 0 then
    redis.call("EXPIRE", KEYS[1], tonumber(ARGV[1]))
end
return count
"""


class _AsyncRedis(Protocol):
    async def eval(self, script: str, numkeys: int, *keys_and_args: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """Outcome of one rate-limit check."""

    allowed: bool
    retry_after_seconds: int
    backend_available: bool


class FixedWindowLimiter:
    """Per-key fixed-window counter backed by an atomic Redis script."""

    def __init__(self, redis: _AsyncRedis) -> None:
        self._redis = redis

    async def consume(
        self,
        *,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        try:
            count = int(
                await self._redis.eval(
                    _INCREMENT_AND_BOUND_WINDOW_SCRIPT,
                    1,
                    key,
                    str(int(window_seconds)),
                )
            )
        except Exception:  # noqa: BLE001 - any Redis error => backend unavailable.
            return RateLimitDecision(
                allowed=False, retry_after_seconds=1, backend_available=False
            )
        if count <= limit:
            return RateLimitDecision(
                allowed=True, retry_after_seconds=0, backend_available=True
            )
        return RateLimitDecision(
            allowed=False,
            retry_after_seconds=max(1, window_seconds),
            backend_available=True,
        )


def fail_open_allowed(method: str) -> bool:
    """When the limiter backend is unavailable, idempotent reads degrade open
    (allow + alert) while state-changing writes fail closed."""
    return method.upper() in _IDEMPOTENT_METHODS


def _problem_body(*, title: str, status: int, detail: str) -> bytes:
    return json.dumps(
        {
            "type": "about:blank",
            "title": title,
            "status": status,
            "detail": detail,
            "code": title,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def too_many_requests_response(*, retry_after_seconds: int) -> Response:
    """A ``429`` problem-details response carrying ``Retry-After``."""
    return Response(
        content=_problem_body(
            title="rate_limited", status=429, detail="Rate limit exceeded."
        ),
        status_code=429,
        media_type=PROBLEM_DETAILS_MEDIA_TYPE,
        headers={"Retry-After": str(max(1, retry_after_seconds))},
    )


def service_unavailable_response() -> Response:
    """A ``503`` response used when the limiter fails closed on backend loss."""
    return Response(
        content=_problem_body(
            title="rate_limit_unavailable",
            status=503,
            detail="Rate limiter temporarily unavailable.",
        ),
        status_code=503,
        media_type=PROBLEM_DETAILS_MEDIA_TYPE,
    )


__all__ = [
    "FixedWindowLimiter",
    "RateLimitDecision",
    "fail_open_allowed",
    "service_unavailable_response",
    "too_many_requests_response",
]
