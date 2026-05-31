"""Failure pattern detection over DLQ and admission records."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.admission import AdmissionRecordRow
from app.events import InMemoryOperationalEventPersistence
from app.execution.db.models import ExecutionRow
from app.execution.enums import ExecutionKind, ExecutionState
from app.runtime.db.models import DeadLetterTaskRow, SOPFailurePatternRow
from app.runtime.failure_pattern_runtime import (
    DLQ_THRESHOLD,
    DLQ_WINDOW_HOURS,
    FailurePattern,
    FailurePatternDetectionRuntime,
)
from app.tenant.db.models import TenantRow
from app.workers.failure_pattern_tasks import detect_sop_failure_patterns_runtime
from tests.conftest import requires_postgres, set_pg_rls_tenant

pytestmark = [pytest.mark.asyncio, requires_postgres]

_NOW = datetime(2026, 5, 30, 8, tzinfo=timezone.utc)
_NAMESPACE = uuid.UUID("a57f8e98-f064-58fd-b444-fc5da9deeb50")


async def test_dlq_pattern_detected_at_threshold(
    pg_session: AsyncSession,
) -> None:
    tenant_id = "tenant-failure-dlq-hit"
    await _seed_dlq_records(
        pg_session,
        tenant_id=tenant_id,
        category="charging_issue",
        count=DLQ_THRESHOLD,
    )
    await set_pg_rls_tenant(pg_session, tenant_id)
    runtime = FailurePatternDetectionRuntime(
        session=pg_session,
        event_persistence=InMemoryOperationalEventPersistence(),
        now=lambda: _NOW,
    )

    patterns = await runtime.detect_dlq_patterns(
        tenant_id=tenant_id,
        expected_tenant_id=tenant_id,
    )

    assert len(patterns) == 1
    assert patterns[0].category == "charging_issue"
    assert patterns[0].failure_count == DLQ_THRESHOLD
    assert patterns[0].pattern_source == "dlq"
    assert set(patterns[0].metadata["trigger_dlq_ids"]) == {
        str(uuid.uuid5(_NAMESPACE, f"dlq:{tenant_id}:charging_issue:{index}"))
        for index in range(DLQ_THRESHOLD)
    }


async def test_dlq_pattern_not_detected_below_threshold(
    pg_session: AsyncSession,
) -> None:
    tenant_id = "tenant-failure-dlq-low"
    await _seed_dlq_records(
        pg_session,
        tenant_id=tenant_id,
        category="charging_issue",
        count=DLQ_THRESHOLD - 1,
    )
    await set_pg_rls_tenant(pg_session, tenant_id)
    runtime = FailurePatternDetectionRuntime(
        session=pg_session,
        event_persistence=InMemoryOperationalEventPersistence(),
        now=lambda: _NOW,
    )

    patterns = await runtime.detect_dlq_patterns(
        tenant_id=tenant_id,
        expected_tenant_id=tenant_id,
    )

    assert patterns == []


async def test_dlq_uses_task_name_when_no_category(
    pg_session: AsyncSession,
) -> None:
    tenant_id = "tenant-failure-dlq-unknown"
    await _seed_dlq_records(
        pg_session,
        tenant_id=tenant_id,
        category=None,
        count=DLQ_THRESHOLD,
    )
    await set_pg_rls_tenant(pg_session, tenant_id)
    runtime = FailurePatternDetectionRuntime(
        session=pg_session,
        event_persistence=InMemoryOperationalEventPersistence(),
        now=lambda: _NOW,
    )

    patterns = await runtime.detect_dlq_patterns(
        tenant_id=tenant_id,
        expected_tenant_id=tenant_id,
    )

    assert len(patterns) == 1
    assert patterns[0].category == "unknown_diagnostic"


async def test_admission_pattern_detected(pg_session: AsyncSession) -> None:
    tenant_id = "tenant-failure-admission-hit"
    await _seed_admission_records(
        pg_session,
        tenant_id=tenant_id,
        channel="voice",
        count=DLQ_THRESHOLD,
    )
    await set_pg_rls_tenant(pg_session, tenant_id)
    runtime = FailurePatternDetectionRuntime(
        session=pg_session,
        event_persistence=InMemoryOperationalEventPersistence(),
        now=lambda: _NOW,
    )

    patterns = await runtime.detect_admission_patterns(
        tenant_id=tenant_id,
        expected_tenant_id=tenant_id,
        threshold=DLQ_THRESHOLD,
    )

    assert len(patterns) == 1
    assert patterns[0].category == "admission_voice"
    assert patterns[0].failure_count == DLQ_THRESHOLD
    assert patterns[0].pattern_source == "admission"
    assert set(patterns[0].metadata["trigger_admission_ids"]) == {
        str(uuid.uuid5(_NAMESPACE, f"admission:{tenant_id}:voice:{index}"))
        for index in range(DLQ_THRESHOLD)
    }


async def test_failure_pattern_stores_trigger_ids(
    pg_session: AsyncSession,
) -> None:
    tenant_id = "tenant-failure-trigger-ids"
    await _seed_dlq_records(
        pg_session,
        tenant_id=tenant_id,
        category="charging_issue",
        count=DLQ_THRESHOLD,
    )
    await set_pg_rls_tenant(pg_session, tenant_id)
    runtime = FailurePatternDetectionRuntime(
        session=pg_session,
        event_persistence=InMemoryOperationalEventPersistence(),
        now=lambda: _NOW,
    )

    patterns = await runtime.detect_dlq_patterns(
        tenant_id=tenant_id,
        expected_tenant_id=tenant_id,
    )
    result = await runtime.record_detected_pattern(
        pattern=patterns[0],
        expected_tenant_id=tenant_id,
        window_hours=DLQ_WINDOW_HOURS,
        threshold=DLQ_THRESHOLD,
    )
    row = (
        await pg_session.execute(
            select(SOPFailurePatternRow).where(
                SOPFailurePatternRow.pattern_id == result.pattern_id
            )
        )
    ).scalar_one()

    assert row.metadata_json["_schema_version"] == "1"
    assert set(row.metadata_json["trigger_dlq_ids"]) == {
        str(uuid.uuid5(_NAMESPACE, f"dlq:{tenant_id}:charging_issue:{index}"))
        for index in range(DLQ_THRESHOLD)
    }


async def test_pattern_persisted_idempotent(
    pg_session: AsyncSession,
) -> None:
    tenant_id = "tenant-failure-idempotent"
    await _ensure_tenant(pg_session, tenant_id)
    await set_pg_rls_tenant(pg_session, tenant_id)
    runtime = FailurePatternDetectionRuntime(
        session=pg_session,
        event_persistence=InMemoryOperationalEventPersistence(),
        now=lambda: _NOW,
    )
    pattern = _pattern(tenant_id=tenant_id)

    first = await runtime.record_detected_pattern(
        pattern=pattern,
        expected_tenant_id=tenant_id,
        window_hours=DLQ_WINDOW_HOURS,
        threshold=DLQ_THRESHOLD,
    )
    second = await runtime.record_detected_pattern(
        pattern=pattern,
        expected_tenant_id=tenant_id,
        window_hours=DLQ_WINDOW_HOURS,
        threshold=DLQ_THRESHOLD,
    )
    row_count = int(
        (
            await pg_session.execute(
                select(func.count()).select_from(SOPFailurePatternRow)
            )
        ).scalar_one()
    )

    assert first.pattern_id == second.pattern_id
    assert first.inserted is True
    assert second.inserted is False
    assert row_count == 1


async def test_propose_called_on_new_pattern(
    pg_session: AsyncSession,
) -> None:
    tenant_id = "tenant-failure-propose"
    await _seed_dlq_records(
        pg_session,
        tenant_id=tenant_id,
        category="charging_issue",
        count=DLQ_THRESHOLD,
    )
    await set_pg_rls_tenant(pg_session, tenant_id)
    fake_runtime = _FakeSOPRuntime()
    fake_synthesis = _FakeSOPSynthesisAgent("Synthesized charging SOP update")

    result = await detect_sop_failure_patterns_runtime(
        tenant_ids=(tenant_id,),
        session=pg_session,
        sop_runtime=fake_runtime,
        sop_synthesis_agent=fake_synthesis,
        event_persistence=InMemoryOperationalEventPersistence(),
        now=lambda: _NOW,
    )
    row = (
        await pg_session.execute(
            select(SOPFailurePatternRow).where(
                SOPFailurePatternRow.tenant_id == tenant_id
            )
        )
    ).scalar_one()

    assert result["patterns_inserted"] == 1
    assert fake_runtime.calls == [
        {
            "tenant_id": tenant_id,
            "expected_tenant_id": tenant_id,
            "category": "charging_issue",
            "recommendation_count": DLQ_THRESHOLD,
            "synthesized_proposed_change": "Synthesized charging SOP update",
            "pattern_id": row.pattern_id,
        }
    ]
    assert row.status == "proposed"
    assert row.sop_proposal_id == fake_runtime.approval_id


async def test_failure_pattern_tenant_isolation(
    pg_session: AsyncSession,
) -> None:
    tenant_a = "tenant-failure-a"
    tenant_b = "tenant-failure-b"
    await _ensure_tenant(pg_session, tenant_a)
    await _ensure_tenant(pg_session, tenant_b)
    await set_pg_rls_tenant(pg_session, tenant_a)
    runtime = FailurePatternDetectionRuntime(
        session=pg_session,
        event_persistence=InMemoryOperationalEventPersistence(),
        now=lambda: _NOW,
    )
    await runtime.record_detected_pattern(
        pattern=_pattern(tenant_id=tenant_a),
        expected_tenant_id=tenant_a,
        window_hours=DLQ_WINDOW_HOURS,
        threshold=DLQ_THRESHOLD,
    )
    try:
        await pg_session.execute(text("SET LOCAL ROLE operious_app_test"))
        await set_pg_rls_tenant(pg_session, tenant_b)
        visible = int(
            (
                await pg_session.execute(
                    select(func.count()).select_from(SOPFailurePatternRow)
                )
            ).scalar_one()
        )
    finally:
        await pg_session.execute(text("RESET ROLE"))

    assert visible == 0


async def _seed_dlq_records(
    session: AsyncSession,
    *,
    tenant_id: str,
    category: str | None,
    count: int,
) -> None:
    await _ensure_tenant(session, tenant_id)
    await set_pg_rls_tenant(session, tenant_id)
    for index in range(count):
        execution_id = uuid.uuid5(
            _NAMESPACE,
            f"execution:{tenant_id}:{category}:{index}",
        )
        session.add(
            ExecutionRow(
                execution_id=execution_id,
                kind=ExecutionKind.DIAGNOSTIC_AGENT.value,
                dispatch_id=f"dispatch-{tenant_id}-{index}",
                session_id=f"session-{tenant_id}-{index}",
                tenant_id=tenant_id,
                state=ExecutionState.DEAD_LETTERED.value,
                attempt_count=3,
                requested_at=_NOW - timedelta(hours=2),
                failed_at=_NOW - timedelta(hours=1),
                diagnostic_category=category,
                diagnostic_confidence=0.2 if category is not None else None,
                result={},
                metadata_json={},
            )
        )
        session.add(
            DeadLetterTaskRow(
                dead_letter_task_id=uuid.uuid5(
                    _NAMESPACE,
                    f"dlq:{tenant_id}:{category}:{index}",
                ),
                tenant_id=tenant_id,
                task_name="execute_diagnostic_agent",
                task_id=f"task-{tenant_id}-{index}",
                execution_id=execution_id,
                queue="diagnostic_normal",
                reason="retry budget exhausted",
                retry_count=3,
                created_at=_NOW - timedelta(minutes=30, seconds=index),
                metadata_json={
                    "execution_id": str(execution_id),
                    "tenant_id": tenant_id,
                    "attempt_count": 3,
                },
            )
        )
    await session.flush()


async def _seed_admission_records(
    session: AsyncSession,
    *,
    tenant_id: str,
    channel: str,
    count: int,
) -> None:
    await _ensure_tenant(session, tenant_id)
    await set_pg_rls_tenant(session, tenant_id)
    for index in range(count):
        session.add(
            AdmissionRecordRow(
                decision_id=uuid.uuid5(
                    _NAMESPACE,
                    f"admission:{tenant_id}:{channel}:{index}",
                ),
                tenant_id=tenant_id,
                outcome="DEFER",
                reason="QUEUE_DEPTH_EXCEEDED",
                queue_name="sop_intelligence",
                queue_depth=1000,
                queue_age_seconds=180.0,
                redis_memory_pct=50.0,
                db_pool_wait_ms=5.0,
                retry_after_seconds=15,
                channel=channel,
                channel_class="async_ticket",
                queue_depth_available=True,
                queue_age_available=True,
                redis_memory_available=True,
                telemetry_unavailable=False,
                unavailable_reasons=[],
                evaluated_at=_NOW - timedelta(minutes=10, seconds=index),
            )
        )
    await session.flush()


async def _ensure_tenant(session: AsyncSession, tenant_id: str) -> None:
    await set_pg_rls_tenant(session, tenant_id)
    await session.merge(TenantRow(tenant_id=tenant_id))
    await session.flush()


def _pattern(tenant_id: str) -> FailurePattern:
    return FailurePattern(
        tenant_id=tenant_id,
        category="charging_issue",
        failure_count=DLQ_THRESHOLD,
        pattern_source="dlq",
        window_start=_NOW - timedelta(hours=DLQ_WINDOW_HOURS),
        window_end=_NOW,
    )


@dataclass(slots=True)
class _Approval:
    approval_id: uuid.UUID


class _FakeSOPRuntime:
    def __init__(self) -> None:
        self.approval_id = uuid.uuid5(_NAMESPACE, "fake-approval")
        self.calls: list[dict[str, Any]] = []

    async def propose_from_failure_pattern(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        category: str,
        recommendation_count: int,
        synthesized_proposed_change: str | None = None,
        pattern_id: str | uuid.UUID | None = None,
    ) -> _Approval:
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "expected_tenant_id": expected_tenant_id,
                "category": category,
                "recommendation_count": recommendation_count,
                "synthesized_proposed_change": synthesized_proposed_change,
                "pattern_id": pattern_id,
            }
        )
        return _Approval(approval_id=self.approval_id)


class _FakeSOPSynthesisAgent:
    def __init__(self, proposed_change: str) -> None:
        self.proposed_change = proposed_change

    async def synthesize_improvement(
        self,
        *,
        category: str,
        failure_count: int,
        failure_description: str,
        tenant_id: str,
    ) -> str:
        del category, failure_count, failure_description, tenant_id
        return self.proposed_change
