"""Operational health orchestration service.

Owns the *policy* layer of the readiness pipeline:

* which dependencies are part of "ready",
* how their probes are dispatched (concurrently, with bounded timeouts),
* how individual results aggregate into an overall verdict,
* what the domain shape of a health report is.

Returns plain domain dataclasses, never Pydantic schemas. Transport
mapping happens in the v1 schema layer.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Sequence

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.health import (
    DependencyCheck,
    aggregate_status,
    check_database,
    check_redis,
)
from app.services.base import BaseService

CheckName = Literal["health", "live", "ready"]
ProbeStatus = Literal["ok", "degraded", "unavailable"]


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
        session_factory: async_sessionmaker[AsyncSession],
        redis: Redis,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._session_factory = session_factory
        self._redis = redis

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
        checks: Sequence[DependencyCheck] = await asyncio.gather(
            check_database(self._session_factory),
            check_redis(self._redis),
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
