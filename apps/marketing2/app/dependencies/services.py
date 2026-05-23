"""Service dependency providers.

Each provider composes one service from its concrete collaborators.
Services are cheap to construct (no state, no caches), so we mint a
fresh instance per request — that keeps them safe to await without
worrying about cross-request leakage.

`HealthService` is special: it owns its own session lifecycle (to run
fan-out probes independently of the request session) and therefore
receives the `async_sessionmaker` rather than an `AsyncSession`. Every
other service in later sprints will receive its repository (bound to
the request session) instead.
"""

from __future__ import annotations

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.redis import get_redis
from app.dependencies.database import get_session_factory
from app.services.health_service import HealthService


def get_health_service(
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> HealthService:
    """Construct `HealthService` with its concrete collaborators."""
    return HealthService(
        settings=settings,
        session_factory=session_factory,
        redis=redis,
    )


__all__ = ["get_health_service"]
