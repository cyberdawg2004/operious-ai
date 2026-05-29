"""Read service for tenant-scoped semantic circuit state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.semantic.events import (
    SemanticCircuitEventRecord,
    SemanticCircuitEventRepository,
)


@dataclass(frozen=True, slots=True)
class SemanticCircuitStateRecord:
    channel: str
    state: str
    cluster_size: int | None
    occurred_at: datetime
    similarity_threshold: float | None
    window_seconds: int | None


class SemanticCircuitService:
    """Tenant-scoped read surface for semantic circuit monitoring."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: SemanticCircuitEventRepository | None = None,
    ) -> None:
        self._repository = repository or SemanticCircuitEventRepository(session)

    async def list_states(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> list[SemanticCircuitStateRecord]:
        records = await self._repository.list_for_tenant(
            tenant_id=tenant_id,
            expected_tenant_id=expected_tenant_id,
            limit=500,
        )
        states: list[SemanticCircuitStateRecord] = []
        seen_channels: set[str] = set()
        for record in records:
            if record.channel in seen_channels:
                continue
            seen_channels.add(record.channel)
            states.append(
                SemanticCircuitStateRecord(
                    channel=record.channel,
                    state=record.state,
                    cluster_size=record.cluster_size,
                    occurred_at=record.occurred_at,
                    similarity_threshold=record.similarity_threshold,
                    window_seconds=record.window_seconds,
                )
            )
        return states

    async def list_events(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        channel: str | None = None,
        limit: int = 50,
    ) -> list[SemanticCircuitEventRecord]:
        return await self._repository.list_for_tenant(
            tenant_id=tenant_id,
            expected_tenant_id=expected_tenant_id,
            channel=channel,
            limit=limit,
        )


__all__ = ["SemanticCircuitService", "SemanticCircuitStateRecord"]
