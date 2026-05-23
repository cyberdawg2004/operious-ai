"""Persistence access for system-health records.

Owns every query that touches `system_health_checks`. Methods are
named for intent (`ping`, `record`, `recent`), not for SQL verbs, so
service-layer code reads as orchestration rather than as a thin
re-export of CRUD.

Sprint D uses `ping()` from the readiness pipeline; `record()` and
`recent()` are wired so the persistence shape is exercised end-to-end
and so the periodic self-check job that lands in a later sprint can
adopt them without adding repository methods.
"""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import select, text

from app.db.models.system_health import SystemHealthCheck
from app.repositories.base import BaseRepository


class SystemHealthRepository(BaseRepository):
    """Queries for the `system_health_checks` table."""

    async def ping(self) -> None:
        """Verify the connection is alive with a trivial `SELECT 1`.

        Reused by the readiness probe. Intentionally does not allocate
        a row, so probe latency is bounded by the round-trip cost.
        """
        await self.session.execute(text("SELECT 1"))

    async def record(
        self,
        *,
        service_name: str,
        status: str,
    ) -> SystemHealthCheck:
        """Persist a single health-check observation.

        Does NOT commit — the calling service owns the transaction.
        Returns the populated entity (id materialised via `flush`).
        """
        entity = SystemHealthCheck(service_name=service_name, status=status)
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def recent(self, *, limit: int = 50) -> Sequence[SystemHealthCheck]:
        """Return the most recent observations, newest first."""
        stmt = (
            select(SystemHealthCheck)
            .order_by(SystemHealthCheck.checked_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


__all__ = ["SystemHealthRepository"]
