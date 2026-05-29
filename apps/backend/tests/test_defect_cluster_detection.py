"""Defect cluster detection runtime tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.events import InMemoryOperationalEventPersistence, OperationalEventQuery
from app.execution import (
    ExecutionResultEnvelope,
    ExecutionRuntime,
    ExecutionState,
    PostgresExecutionPersistence,
)
from app.execution.db.models import ExecutionRow
from app.execution.enums import ExecutionKind
from app.governance.capability.acts import OperationalAct
from app.runtime.defect_cluster_runtime import (
    CLUSTER_THRESHOLD,
    DefectClusterCandidate,
    DefectClusterDetectionRuntime,
)
from app.runtime.db.models import DefectClusterRow
from app.tenant.db.models import TenantRow
from tests.conftest import (
    execution_admission_token,
    requires_postgres,
    set_pg_rls_tenant,
)

_NOW = datetime(2026, 5, 30, 8, tzinfo=timezone.utc)

pytestmark = [pytest.mark.asyncio, requires_postgres]


async def test_execution_category_populated_at_completion(
    pg_session: AsyncSession,
) -> None:
    await set_pg_rls_tenant(pg_session, "tenant-defect-column")
    runtime = ExecutionRuntime(
        persistence=PostgresExecutionPersistence(pg_session)
    )
    requested = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-defect-column",
        session_id="session-defect-column",
        tenant_id="tenant-defect-column",
        requested_at=_NOW,
        admission_token=execution_admission_token(
            tenant_id="tenant-defect-column",
            admitted_at=_NOW,
        ),
    )
    claimed = await runtime.claim_execution(
        execution_id=requested.execution.execution_id,
        worker_id="worker-defect-column",
        claimed_at=_NOW,
    )
    assert claimed.attempt is not None

    await runtime.complete_execution(
        execution_id=requested.execution.execution_id,
        attempt_id=claimed.attempt.attempt_id,
        worker_id="worker-defect-column",
        result=ExecutionResultEnvelope(
            diagnostic_category="charging_issue",
            diagnostic_confidence=0.91,
            diagnostic_summary="charging issue",
        ).to_dict(),
        completed_at=_NOW,
        diagnostic_category="charging_issue",
        diagnostic_confidence=0.91,
    )
    row = await pg_session.get(
        ExecutionRow,
        uuid.UUID(str(requested.execution.execution_id)),
    )

    assert row is not None
    assert row.diagnostic_category == "charging_issue"
    assert row.diagnostic_confidence == 0.91


async def test_cluster_detected_at_threshold(
    pg_session: AsyncSession,
) -> None:
    await _seed_executions(
        pg_session,
        tenant_id="tenant-cluster-hit",
        category="charging_issue",
        count=CLUSTER_THRESHOLD,
        requested_at=_NOW - timedelta(hours=1),
    )
    await set_pg_rls_tenant(pg_session, "tenant-cluster-hit")
    runtime = DefectClusterDetectionRuntime(session=pg_session, now=lambda: _NOW)

    candidates = await runtime.scan_tenant(
        tenant_id="tenant-cluster-hit",
        expected_tenant_id="tenant-cluster-hit",
    )

    assert len(candidates) == 1
    assert candidates[0].category == "charging_issue"
    assert candidates[0].execution_count == CLUSTER_THRESHOLD
    assert len(candidates[0].execution_ids) == CLUSTER_THRESHOLD


async def test_cluster_not_detected_below_threshold(
    pg_session: AsyncSession,
) -> None:
    await _seed_executions(
        pg_session,
        tenant_id="tenant-cluster-low",
        category="charging_issue",
        count=CLUSTER_THRESHOLD - 1,
        requested_at=_NOW - timedelta(hours=1),
    )
    await set_pg_rls_tenant(pg_session, "tenant-cluster-low")
    runtime = DefectClusterDetectionRuntime(session=pg_session, now=lambda: _NOW)

    candidates = await runtime.scan_tenant(
        tenant_id="tenant-cluster-low",
        expected_tenant_id="tenant-cluster-low",
    )

    assert candidates == []


async def test_cluster_emission_is_idempotent(
    pg_session: AsyncSession,
) -> None:
    event_store = InMemoryOperationalEventPersistence()
    await _ensure_tenant(pg_session, "tenant-cluster-event")
    await set_pg_rls_tenant(pg_session, "tenant-cluster-event")
    candidate = DefectClusterCandidate(
        tenant_id="tenant-cluster-event",
        category="charging_issue",
        execution_count=CLUSTER_THRESHOLD,
        window_start=_NOW - timedelta(hours=1),
        window_end=_NOW,
        execution_ids=tuple(f"execution-{i}" for i in range(CLUSTER_THRESHOLD)),
        threshold_used=CLUSTER_THRESHOLD,
    )
    runtime = DefectClusterDetectionRuntime(
        session=pg_session,
        event_persistence=event_store,
        now=lambda: _NOW,
    )

    first = await runtime.emit_cluster_event(
        candidate=candidate,
        expected_tenant_id="tenant-cluster-event",
    )
    second = await runtime.emit_cluster_event(
        candidate=candidate,
        expected_tenant_id="tenant-cluster-event",
    )
    cluster_count = int(
        (
            await pg_session.execute(
                select(func.count()).select_from(DefectClusterRow)
            )
        ).scalar_one()
    )
    events = await event_store.list_events(
        OperationalEventQuery(
            operational_act=OperationalAct.DEFECT_CLUSTER_DETECTED,
            tenant_id="tenant-cluster-event",
        )
    )

    assert first == second
    assert cluster_count == 1
    assert events.total == 1
    assert events.events[0].metadata["cluster_id"] == first


async def test_cluster_outside_window_not_counted(
    pg_session: AsyncSession,
) -> None:
    await _seed_executions(
        pg_session,
        tenant_id="tenant-cluster-old",
        category="charging_issue",
        count=CLUSTER_THRESHOLD,
        requested_at=_NOW - timedelta(hours=25),
    )
    await set_pg_rls_tenant(pg_session, "tenant-cluster-old")
    runtime = DefectClusterDetectionRuntime(session=pg_session, now=lambda: _NOW)

    candidates = await runtime.scan_tenant(
        tenant_id="tenant-cluster-old",
        expected_tenant_id="tenant-cluster-old",
        window_hours=24,
    )

    assert candidates == []


async def test_cluster_tenant_isolation(
    pg_session: AsyncSession,
) -> None:
    await _seed_executions(
        pg_session,
        tenant_id="tenant-a",
        category="charging_issue",
        count=CLUSTER_THRESHOLD,
        requested_at=_NOW - timedelta(hours=1),
    )
    await _ensure_tenant(pg_session, "tenant-b")
    await set_pg_rls_tenant(pg_session, "tenant-b")
    runtime = DefectClusterDetectionRuntime(session=pg_session, now=lambda: _NOW)

    candidates = await runtime.scan_tenant(
        tenant_id="tenant-b",
        expected_tenant_id="tenant-b",
    )

    assert candidates == []


async def _seed_executions(
    session: AsyncSession,
    *,
    tenant_id: str,
    category: str,
    count: int,
    requested_at: datetime,
) -> None:
    await set_pg_rls_tenant(session, tenant_id)
    await _ensure_tenant(session, tenant_id)
    for index in range(count):
        execution_id = uuid.uuid5(
            uuid.UUID("2f6ff4d7-d7b0-55d0-96c9-089b34fda17a"),
            f"{tenant_id}|{category}|{requested_at.isoformat()}|{index}",
        )
        session.add(
            ExecutionRow(
                execution_id=execution_id,
                kind=ExecutionKind.DIAGNOSTIC_AGENT.value,
                dispatch_id=f"dispatch-{execution_id}",
                session_id=f"session-{execution_id}",
                tenant_id=tenant_id,
                state=ExecutionState.COMPLETED.value,
                attempt_count=1,
                requested_at=requested_at + timedelta(minutes=index),
                completed_at=requested_at + timedelta(minutes=index, seconds=30),
                diagnostic_category=category,
                diagnostic_confidence=0.9,
                result=ExecutionResultEnvelope(
                    diagnostic_category=category,
                    diagnostic_confidence=0.9,
                    diagnostic_summary=f"{category} summary",
                ).to_dict(),
                metadata_json={},
            )
        )
    await session.flush()


async def _ensure_tenant(session: AsyncSession, tenant_id: str) -> None:
    await set_pg_rls_tenant(session, tenant_id)
    await session.merge(TenantRow(tenant_id=tenant_id))
    await session.flush()
