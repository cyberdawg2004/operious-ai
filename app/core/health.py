"""Health-probe primitives.

A tiny library of building blocks the service layer composes into
readiness logic. Nothing here knows about HTTP, persistence policy, or
business rules.

After Sprint D the database probe lives in
`app.repositories.system_health_repository` (query) and
`app.services.health_service` (policy). What remains here:

* `DependencyCheck`   — frozen result type for a single probe.
* `run_with_timeout`  — bounded-execution helper that turns any
                        async coroutine into a `DependencyCheck`,
                        capturing exceptions and timing.
* `check_redis`       — the one external-system probe that doesn't
                        justify its own repository (single primitive,
                        no query surface).
* `aggregate_status`  — rolls individual results into the overall
                        ok / degraded / unavailable verdict.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

from redis.asyncio import Redis

from app.core.logging import get_logger

logger = get_logger(__name__)

CheckStatus = Literal["ok", "unavailable"]


@dataclass(frozen=True, slots=True)
class DependencyCheck:
    name: str
    status: CheckStatus
    latency_ms: float
    error: str | None = None


async def run_with_timeout(
    *,
    name: str,
    coro_factory: Callable[[], Awaitable[None]],
    timeout: float,
) -> DependencyCheck:
    """Run a probe coroutine, capturing latency, exceptions, and timeouts."""
    loop = asyncio.get_event_loop()
    started = loop.time()
    try:
        await asyncio.wait_for(coro_factory(), timeout=timeout)
        elapsed_ms = (loop.time() - started) * 1000
        return DependencyCheck(name=name, status="ok", latency_ms=round(elapsed_ms, 2))
    except Exception as exc:  # noqa: BLE001 — health checks must swallow
        elapsed_ms = (loop.time() - started) * 1000
        logger.warning(
            "dependency_check_failed",
            extra={"dependency": name, "error": str(exc)},
        )
        return DependencyCheck(
            name=name,
            status="unavailable",
            latency_ms=round(elapsed_ms, 2),
            error=type(exc).__name__,
        )


async def check_redis(client: Redis, timeout: float = 2.0) -> DependencyCheck:
    """`PING` against the shared async Redis client."""

    async def _ping() -> None:
        await client.ping()

    return await run_with_timeout(name="redis", coro_factory=_ping, timeout=timeout)


def aggregate_status(
    checks: list[DependencyCheck],
) -> Literal["ok", "degraded", "unavailable"]:
    """Roll individual dependency results into an overall status.

    * all ok       → ok
    * some failing → degraded
    * all failing  → unavailable
    """
    if not checks:
        return "ok"
    failed = sum(1 for c in checks if c.status != "ok")
    if failed == 0:
        return "ok"
    if failed == len(checks):
        return "unavailable"
    return "degraded"


__all__ = [
    "DependencyCheck",
    "run_with_timeout",
    "check_redis",
    "aggregate_status",
]
