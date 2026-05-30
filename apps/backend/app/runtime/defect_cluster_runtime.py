"""Defect cluster detection over completed diagnostic executions."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.events import (
    EventCausality,
    EventChronology,
    OperationalEvent,
    OperationalSubstrate,
    derive_event_id,
)
from app.events.persistence import (
    OperationalEventPersistenceProtocol,
    PostgresOperationalEventPersistence,
)
from app.execution.db.models import ExecutionRow
from app.execution.enums import ExecutionState
from app.governance.capability.acts import OperationalAct
from app.runtime.db.models import DefectClusterRow

CLUSTER_WINDOW_HOURS: int = 24
CLUSTER_THRESHOLD: int = 5

_CLUSTER_NAMESPACE = uuid.UUID("d44b8b59-2b72-55f9-9d52-a6e80e31f5a8")


@dataclass(frozen=True, slots=True)
class DefectClusterCandidate:
    tenant_id: str
    category: str
    execution_count: int
    window_start: datetime
    window_end: datetime
    execution_ids: tuple[str, ...]
    window_hours: int = CLUSTER_WINDOW_HOURS
    threshold_used: int = CLUSTER_THRESHOLD


class DefectClusterDetectionRuntime:
    """Detect and emit category clusters over completed diagnostics."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        event_persistence: OperationalEventPersistenceProtocol | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._event_persistence = (
            event_persistence
            if event_persistence is not None
            else PostgresOperationalEventPersistence(session)
        )
        self._now = now or _utcnow

    async def scan_tenant(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        window_hours: int = CLUSTER_WINDOW_HOURS,
        threshold: int = CLUSTER_THRESHOLD,
    ) -> list[DefectClusterCandidate]:
        if tenant_id != expected_tenant_id:
            raise ValueError("tenant_id does not match expected_tenant_id")
        if window_hours < 1:
            raise ValueError("window_hours must be >= 1")
        if threshold < 1:
            raise ValueError("threshold must be >= 1")

        now = _coerce_aware(self._now())
        window_floor = now - timedelta(hours=window_hours)
        count_expr = func.count(ExecutionRow.execution_id)
        stmt = (
            select(
                ExecutionRow.diagnostic_category,
                count_expr.label("execution_count"),
                func.min(ExecutionRow.requested_at).label("window_start"),
                func.max(ExecutionRow.requested_at).label("window_end"),
            )
            .where(
                ExecutionRow.tenant_id == tenant_id,
                ExecutionRow.state == ExecutionState.COMPLETED.value,
                ExecutionRow.diagnostic_category.is_not(None),
                ExecutionRow.requested_at >= window_floor,
                ExecutionRow.requested_at <= now,
            )
            .group_by(ExecutionRow.diagnostic_category)
            .having(count_expr >= threshold)
        )
        rows = (await self._session.execute(stmt)).all()
        candidates: list[DefectClusterCandidate] = []
        for row in rows:
            category = cast(str | None, row[0])
            if category is None:
                continue
            execution_count = int(row[1])
            window_start = _coerce_aware(cast(datetime, row[2]))
            window_end = _coerce_aware(cast(datetime, row[3]))
            execution_ids = await self._execution_ids_for_category(
                tenant_id=tenant_id,
                category=category,
                window_floor=window_floor,
                window_ceiling=now,
            )
            candidates.append(
                DefectClusterCandidate(
                    tenant_id=tenant_id,
                    category=category,
                    execution_count=execution_count,
                    window_start=window_start,
                    window_end=window_end,
                    execution_ids=execution_ids,
                    window_hours=window_hours,
                    threshold_used=threshold,
                )
            )
        return candidates

    async def emit_cluster_event(
        self,
        *,
        candidate: DefectClusterCandidate,
        expected_tenant_id: str,
    ) -> str:
        if candidate.tenant_id != expected_tenant_id:
            raise ValueError("candidate tenant_id does not match expected_tenant_id")

        cluster_id = derive_defect_cluster_id(
            tenant_id=candidate.tenant_id,
            category=candidate.category,
            window_start=candidate.window_start,
            threshold=candidate.threshold_used,
        )
        existing = await self._session.get(DefectClusterRow, cluster_id)
        if existing is not None:
            return str(cluster_id)

        row = DefectClusterRow(
            cluster_id=cluster_id,
            tenant_id=candidate.tenant_id,
            category=candidate.category,
            execution_count=candidate.execution_count,
            window_hours=candidate.window_hours,
            window_start=candidate.window_start,
            window_end=candidate.window_end,
            threshold_used=candidate.threshold_used,
            sku_hint=None,
            failure_step_hint=None,
            status="detected",
            metadata_json={
                "_schema_version": "1",
                "execution_ids": list(candidate.execution_ids),
            },
        )
        inserted = False
        try:
            async with self._session.begin_nested():
                self._session.add(row)
                await self._session.flush()
                inserted = True
        except IntegrityError:
            inserted = False

        if inserted:
            await self._event_persistence.append_event(
                _defect_cluster_detected_event(
                    cluster_id=cluster_id,
                    candidate=candidate,
                )
            )
        return str(cluster_id)

    async def _execution_ids_for_category(
        self,
        *,
        tenant_id: str,
        category: str,
        window_floor: datetime,
        window_ceiling: datetime,
    ) -> tuple[str, ...]:
        stmt = (
            select(ExecutionRow.execution_id)
            .where(
                ExecutionRow.tenant_id == tenant_id,
                ExecutionRow.state == ExecutionState.COMPLETED.value,
                ExecutionRow.diagnostic_category == category,
                ExecutionRow.requested_at >= window_floor,
                ExecutionRow.requested_at <= window_ceiling,
            )
            .order_by(ExecutionRow.requested_at, ExecutionRow.execution_id)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(str(value) for value in rows)


def derive_defect_cluster_id(
    *,
    tenant_id: str,
    category: str,
    window_start: datetime,
    threshold: int,
) -> uuid.UUID:
    seed = "|".join(
        [
            tenant_id,
            category,
            _coerce_aware(window_start).isoformat(),
            str(threshold),
        ]
    )
    return uuid.uuid5(_CLUSTER_NAMESPACE, seed)


def _defect_cluster_detected_event(
    *,
    cluster_id: uuid.UUID,
    candidate: DefectClusterCandidate,
) -> OperationalEvent:
    runtime_instance_id = uuid.uuid5(
        _CLUSTER_NAMESPACE,
        f"{cluster_id}:runtime",
    )
    sequence = 0
    event_id = derive_event_id(
        operational_act=OperationalAct.DEFECT_CLUSTER_DETECTED.value,
        substrate=OperationalSubstrate.SUPERVISOR.value,
        runtime_instance_id=runtime_instance_id,
        sequence=sequence,
        tenant_id=candidate.tenant_id,
        parent_event_id=None,
    )
    metadata: dict[str, Any] = {
        "_schema_version": "1",
        "cluster_id": str(cluster_id),
        "tenant_id": candidate.tenant_id,
        "category": candidate.category,
        "execution_count": candidate.execution_count,
        "window_hours": candidate.window_hours,
        "window_start": candidate.window_start.isoformat(),
        "window_end": candidate.window_end.isoformat(),
        "threshold_used": candidate.threshold_used,
        "execution_ids": list(candidate.execution_ids),
    }
    return OperationalEvent(
        event_id=event_id,
        operational_act=OperationalAct.DEFECT_CLUSTER_DETECTED,
        substrate=OperationalSubstrate.SUPERVISOR,
        causality=EventCausality(root_event_id=event_id),
        chronology=EventChronology(
            runtime_instance_id=runtime_instance_id,
            sequence=sequence,
            occurred_at=candidate.window_end,
        ),
        tenant_id=candidate.tenant_id,
        metadata=metadata,
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "CLUSTER_THRESHOLD",
    "CLUSTER_WINDOW_HOURS",
    "DefectClusterCandidate",
    "DefectClusterDetectionRuntime",
    "derive_defect_cluster_id",
]
