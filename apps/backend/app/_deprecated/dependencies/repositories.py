"""Repository dependency providers.

One provider per repository. Each binds a repository to the
request-scoped `AsyncSession`, so any consumer of `Depends(get_*_repository)`
automatically participates in the same unit of work.

Concrete repositories are NOT auto-discovered; new ones are wired here
explicitly. That keeps the dependency graph reviewable and prevents
accidental coupling through magic registries.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.database import get_db_session
from app.repositories.system_health_repository import SystemHealthRepository


def get_system_health_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SystemHealthRepository:
    """Bind `SystemHealthRepository` to the request-scoped session."""
    return SystemHealthRepository(session)


__all__ = ["get_system_health_repository"]
