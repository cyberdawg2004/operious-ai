"""Operational health orchestration service.

Owns the *policy* layer of the readiness pipeline:

* which dependencies are part of "ready",
* how their probes are dispatched (concurrently, with bounded timeouts),
* how individual results aggregate into an overall verdict,
* what the domain shape of a health report is.

Persistence access — actually running `SELECT 1` — is delegated to
`SystemHealthRepository`. The service still owns session lifecycle for
the probes because readiness must fail closed independently of the
request session: an exhausted pool or a downed database has to surface
as a degraded probe, not as a 500 from the dependency graph.

Returns plain domain dataclasses, never Pydantic schemas. Transport
mapping happens in the v1 schema layer.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Sequence

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.health import (
    DependencyCheck,
    aggregate_status,
    check_redis,
    run_with_timeout,
)
from app.repositories.system_health_repository import SystemHealthRepository
from app.services.base import BaseService

CheckName = Literal["health", "live", "ready"]
ProbeStatus = Literal["ok", "degraded", "unavailable"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DependencyReport:
    """Domain view of a single dependency probe result."""

    name: str
    status: Literal["ok", "unavailable"]
    latency_ms: float
    error: str | None = None

    @classmethod
    def from_check(cls, check: DependencyCheck) -> "DependencyReport":
        return cls(
            name=check.name,
            status=check.status,
            latency_ms=check.latency_ms,
            error=check.error,
        )


@dataclass(frozen=True, slots=True)
class HealthReport:
    """Domain view of an entire probe result.

    Shape is intentionally transport-agnostic so the same report can be
    returned from HTTP endpoints, persisted as `SystemHealthCheck` rows,
    emitted into observability pipelines, or consumed by orchestration
    runtimes.
    """

    check: CheckName
    status: ProbeStatus
    app: str
    version: str
    environment: str
    timestamp: datetime
    dependencies: tuple[DependencyReport, ...] = field(default_factory=tuple)


class HealthService(BaseService):
    """Health/readiness orchestrator.

    Constructor takes every concrete collaborator explicitly — no module
    globals, no hidden singletons. Each FastAPI request constructs a
    fresh instance through dependency injection, so tests can pass fakes
    without monkeypatching.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        redis: Redis | None = None,
        session_factory_provider: (
            Callable[[], async_sessionmaker[AsyncSession]] | None
        ) = None,
        redis_provider: Callable[[], Redis] | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._session_factory_provider = (
            session_factory_provider
            if session_factory_provider is not None
            else lambda: _require_session_factory(session_factory)
        )
        self._redis_provider = (
            redis_provider
            if redis_provider is not None
            else lambda: _require_redis(redis)
        )

    # ─── Public API ────────────────────────────────────────────────────

    async def health(self) -> HealthReport:
        """Cheap, dependency-free health snapshot."""
        return self._build_report(check="health", status="ok", dependencies=())

    async def liveness(self) -> HealthReport:
        """Liveness probe — process responsiveness only.

        MUST NOT touch external dependencies. A dead database must not
        cause a pod to be restarted by an orchestrator's liveness loop.
        """
        return self._build_report(check="live", status="ok", dependencies=())

    async def readiness(self) -> HealthReport:
        """Readiness probe — fan-out all dependency probes concurrently.

        Concurrency caps the worst-case latency at the slowest single
        probe instead of summing them, which materially affects probe
        timeouts in orchestrators under partial-degradation conditions.
        """
        probe_timeout = self._settings.SURVIVABILITY_READINESS_PROBE_TIMEOUT_SECONDS
        readiness_timeout = probe_timeout + 0.5
        logger.info(
            "readiness_probe_begin",
            extra={
                "probe_timeout_seconds": probe_timeout,
                "readiness_timeout_seconds": readiness_timeout,
            },
        )
        try:
            checks: Sequence[DependencyCheck] = await asyncio.wait_for(
                asyncio.gather(
                    self._probe_database(timeout=probe_timeout),
                    self._probe_redis(timeout=probe_timeout),
                ),
                timeout=readiness_timeout,
            )
        except TimeoutError:
            self.logger.warning(
                "readiness_probe_timeout",
                extra={"readiness_timeout_seconds": readiness_timeout},
            )
            checks = (
                DependencyCheck(
                    name="postgres",
                    status="unavailable",
                    latency_ms=round(readiness_timeout * 1000, 2),
                    error="TimeoutError",
                ),
                DependencyCheck(
                    name="redis",
                    status="unavailable",
                    latency_ms=round(readiness_timeout * 1000, 2),
                    error="TimeoutError",
                ),
            )
        overall = aggregate_status(list(checks))
        dependencies = tuple(DependencyReport.from_check(c) for c in checks)

        if overall != "ok":
            self.logger.warning(
                "readiness_degraded",
                extra={
                    "overall_status": overall,
                    "failed": [d.name for d in dependencies if d.status != "ok"],
                },
            )

        return self._build_report(
            check="ready",
            status=overall,
            dependencies=dependencies,
        )

    # ─── Internals ─────────────────────────────────────────────────────

    async def _probe_database(self, *, timeout: float) -> DependencyCheck:
        """Run a connectivity probe via the system-health repository.

        Owns its own session lifecycle so a degraded pool surfaces as a
        captured `DependencyCheck` rather than as an exception that
        bubbles out of FastAPI's dependency graph.
        """

        async def _ping() -> None:
            session_factory = self._session_factory_provider()
            async with session_factory() as session:
                repo = SystemHealthRepository(session)
                await repo.ping()

        return await run_with_timeout(
            name="postgres",
            coro_factory=_ping,
            timeout=timeout,
        )

    async def _probe_redis(self, *, timeout: float) -> DependencyCheck:
        """Run a bounded Redis readiness probe."""

        return await check_redis(self._redis_provider(), timeout=timeout)

    def _build_report(
        self,
        *,
        check: CheckName,
        status: ProbeStatus,
        dependencies: tuple[DependencyReport, ...],
    ) -> HealthReport:
        return HealthReport(
            check=check,
            status=status,
            app=self._settings.APP_NAME,
            version=self._settings.APP_VERSION,
            environment=self._settings.ENVIRONMENT,
            timestamp=datetime.now(timezone.utc),
            dependencies=dependencies,
        )


__all__ = [
    "DependencyReport",
    "HealthReport",
    "HealthService",
]


def _require_session_factory(
    session_factory: async_sessionmaker[AsyncSession] | None,
) -> async_sessionmaker[AsyncSession]:
    if session_factory is None:
        raise RuntimeError("HealthService requires a session factory provider")
    return session_factory


def _require_redis(redis: Redis | None) -> Redis:
    if redis is None:
        raise RuntimeError("HealthService requires a Redis provider")
    return redis
