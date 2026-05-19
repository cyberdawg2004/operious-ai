"""Service / repository dependency providers.

Each provider composes one substrate-shaped dependency from its
concrete collaborators (request-scoped ``AsyncSession``, settings,
shared infra clients). Providers are cheap to construct (no state,
no caches), so we mint a fresh instance per request — that keeps
them safe to await without worrying about cross-request leakage.

Doctrine
────────

* **Routers depend on the Protocol type**, never the concrete
  Postgres class. ``Depends(get_governance_repository)`` is annotated
  ``-> BaseGovernanceRepository`` so handlers cannot import
  ``PostgresGovernanceRepository`` directly — the composition root
  is the single seam between "what the router needs" and "which
  backend currently satisfies it". This is what enables PR-B1's
  in-memory ↔ Postgres swap doctrine to land at runtime without
  touching any router.
* **No service-layer caching**. Repositories close their session
  (via the request-scoped ``get_db_session`` provider) at request
  end. Stale-cache hazards do not exist at this layer.
* **No raw HTTP** in providers. Network-touching dependencies
  (Auth0 JWKS fetch, Redis pings) live in their own modules and
  are constructed at app-boot via the composition root, not via
  request-scoped providers — once-per-request fetches against
  external services are a substrate-wide performance footgun
  the platform refuses by construction.

Phase 3.2 substrate factories
─────────────────────────────

Every substrate that landed a Postgres backend in PR-B2..B7 gets
exactly one factory here. Routers reach the substrate's
persistence Protocol via ``Depends(get_<substrate>_repository)``.
Adding a substrate is additive — never modify an existing factory
to widen its surface.
"""

from __future__ import annotations

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.arbitration.persistence import (
    ArbitrationPersistenceProtocol,
    PostgresArbitrationPersistence,
)
from app.boundary.persistence import (
    BoundaryPersistenceProtocol,
    PostgresBoundaryPersistence,
)
from app.coordination.persistence import (
    CoordinationPersistenceProtocol,
    PostgresCoordinationPersistence,
)
from app.core.config import Settings, get_settings
from app.core.redis import get_redis
from app.dependencies.database import get_db_session, get_session_factory
from app.governance.persistence import (
    BaseGovernanceRepository,
    PostgresGovernanceRepository,
)
from app.services.health_service import HealthService
from app.session.persistence import (
    PostgresSessionPersistence,
    SessionPersistenceProtocol,
)
from app.supervisor.persistence import (
    BaseSupervisorRepository,
    PostgresSupervisorRepository,
)


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


# ─── Phase 3.2 substrate repository factories ───────────────────────────


def get_governance_repository(
    session: AsyncSession = Depends(get_db_session),
) -> BaseGovernanceRepository:
    """Return the Postgres governance repository for this request.

    Return type is annotated to the Protocol so handlers cannot
    accidentally couple to the concrete backend.
    """
    return PostgresGovernanceRepository(session)


def get_session_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SessionPersistenceProtocol:
    """Return the Postgres session-persistence backend for this request."""
    return PostgresSessionPersistence(session)


def get_coordination_repository(
    session: AsyncSession = Depends(get_db_session),
) -> CoordinationPersistenceProtocol:
    """Return the Postgres coordination-persistence backend for this request."""
    return PostgresCoordinationPersistence(session)


def get_arbitration_repository(
    session: AsyncSession = Depends(get_db_session),
) -> ArbitrationPersistenceProtocol:
    """Return the Postgres arbitration-persistence backend for this request."""
    return PostgresArbitrationPersistence(session)


def get_boundary_repository(
    session: AsyncSession = Depends(get_db_session),
) -> BoundaryPersistenceProtocol:
    """Return the Postgres boundary-persistence backend for this request."""
    return PostgresBoundaryPersistence(session)


def get_supervisor_repository(
    session: AsyncSession = Depends(get_db_session),
) -> BaseSupervisorRepository:
    """Return the Postgres supervisor-persistence backend for this request."""
    return PostgresSupervisorRepository(session)


__all__ = [
    "get_arbitration_repository",
    "get_boundary_repository",
    "get_coordination_repository",
    "get_governance_repository",
    "get_health_service",
    "get_session_repository",
    "get_supervisor_repository",
]
