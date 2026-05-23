"""Phase 6-C distributed runtime resilience tests."""

from __future__ import annotations

import ast
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.boundary.enums import (
    BoundaryDirection,
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.identity import BoundaryIngressId
from app.boundary.persistence.records import BoundaryIngressRecord
from app.execution import (
    ExecutionKind,
    ExecutionOutboxState,
    ExecutionRuntime,
    ExecutionState,
    InMemoryExecutionPersistence,
    OutboxQuery,
)
from app.execution.identity import ExecutionId
from app.execution.persistence.records import ExecutionRecord
from app.observability.persistence import (
    InMemoryOperationalObservabilityPersistence,
    InboundNormalizationDeadLetterQuery,
    StuckExecutionAlertQuery,
)
from app.observability.runtime import OperationalObservabilityRuntime
from tests.conftest import execution_admission_token

_BASE = datetime(2026, 5, 23, 8, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_stale_outbox_reconciler_requeues_only_tenant_scope() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    tenant_a = await _publishing_outbox(
        runtime,
        tenant_id="tenant-a",
        dispatch_id="dispatch-a",
        claimed_at=_BASE - timedelta(minutes=30),
    )
    tenant_b = await _publishing_outbox(
        runtime,
        tenant_id="tenant-b",
        dispatch_id="dispatch-b",
        claimed_at=_BASE - timedelta(minutes=30),
    )

    sweep = await runtime.reconcile_stale_outbox_records(
        stale_before=_BASE - timedelta(minutes=5),
        requeued_at=_BASE,
        tenant_id="tenant-a",
        reason="publisher lease expired",
    )
    own_page = await runtime.list_outbox(
        OutboxQuery(tenant_id="tenant-a"),
        expected_tenant_id="tenant-a",
    )
    other_page = await runtime.list_outbox(
        OutboxQuery(tenant_id="tenant-b"),
        expected_tenant_id="tenant-b",
    )

    assert sweep.scanned == 1
    assert sweep.reconciled_count == 1
    assert sweep.refused_count == 0
    assert own_page.records[0].outbox_id == tenant_a.outbox_id
    assert own_page.records[0].state is ExecutionOutboxState.PENDING
    assert own_page.records[0].claimed_at is None
    assert own_page.records[0].publisher_id is None
    assert own_page.records[0].publish_attempt_count == 1
    assert own_page.records[0].last_error == "publisher lease expired"
    assert other_page.records[0].outbox_id == tenant_b.outbox_id
    assert other_page.records[0].state is ExecutionOutboxState.PUBLISHING


@pytest.mark.asyncio
async def test_outbox_reconciler_refuses_fresh_or_cross_tenant_claims() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    own = await _publishing_outbox(
        runtime,
        tenant_id="tenant-a",
        dispatch_id="dispatch-fresh",
        claimed_at=_BASE - timedelta(seconds=10),
    )

    fresh = await runtime.reconcile_stale_outbox(
        outbox_id=own.outbox_id,
        stale_before=_BASE - timedelta(minutes=5),
        requeued_at=_BASE,
        expected_tenant_id="tenant-a",
    )
    cross = await runtime.reconcile_stale_outbox(
        outbox_id=own.outbox_id,
        stale_before=_BASE,
        requeued_at=_BASE,
        expected_tenant_id="tenant-b",
    )

    assert fresh.reconciled is False
    assert fresh.reason == "outbox_not_stale"
    assert cross.reconciled is False
    assert cross.outbox is None
    assert cross.reason == "outbox_not_found"


@pytest.mark.asyncio
async def test_stuck_execution_alerts_are_tenant_scoped_and_deterministic() -> None:
    runtime = _observability_runtime()
    query = StuckExecutionAlertQuery(
        claimed_before_or_at=_BASE - timedelta(minutes=5)
    )

    first = await runtime.list_stuck_execution_alerts(
        query=query,
        expected_tenant_id="tenant-a",
    )
    second = await runtime.list_stuck_execution_alerts(
        query=query,
        expected_tenant_id="tenant-a",
    )
    other = await runtime.list_stuck_execution_alerts(
        query=query,
        expected_tenant_id="tenant-b",
    )

    assert first == second
    assert first.total == 1
    assert first.items[0].tenant_id == "tenant-a"
    assert first.items[0].reason == "execution_claim_exceeded_lease"
    assert uuid.UUID(str(first.items[0].alert_id)).version == 5
    assert other.total == 1
    assert other.items[0].tenant_id == "tenant-b"


@pytest.mark.asyncio
async def test_inbound_normalization_dlq_is_tenant_scoped() -> None:
    runtime = _observability_runtime()

    own = await runtime.list_inbound_normalization_dead_letters(
        query=InboundNormalizationDeadLetterQuery(),
        expected_tenant_id="tenant-a",
    )
    other = await runtime.list_inbound_normalization_dead_letters(
        query=InboundNormalizationDeadLetterQuery(),
        expected_tenant_id="tenant-b",
    )
    filtered = await runtime.list_inbound_normalization_dead_letters(
        query=InboundNormalizationDeadLetterQuery(
            normalization_status=BoundaryNormalizationStatus.MALFORMED.value
        ),
        expected_tenant_id="tenant-a",
    )

    assert own.total == 1
    assert own.items[0].tenant_id == "tenant-a"
    assert own.items[0].normalization_status == "malformed"
    assert own.items[0].error == "missing body"
    assert other.total == 1
    assert other.items[0].tenant_id == "tenant-b"
    assert filtered.total == 1


def test_resilience_router_surfaces_stay_behind_service_boundary() -> None:
    router_path = _repo_root() / "apps/backend/app/api/v1/routers/observability.py"
    tree = ast.parse(router_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    text = router_path.read_text(encoding="utf-8")

    assert "app.observability.persistence" not in imported_modules
    assert "app.observability.runtime" not in imported_modules
    assert "PostgresOperationalObservabilityPersistence" not in text
    assert "OperationalObservabilityRuntime" not in text
    assert "list_stuck_execution_alerts" in text
    assert "list_inbound_normalization_dead_letters" in text


def test_execution_recovery_worker_remains_transport_only() -> None:
    worker_path = _repo_root() / "apps/backend/app/workers/execution_recovery_tasks.py"
    tree = ast.parse(worker_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    text = worker_path.read_text(encoding="utf-8")

    assert "app.execution.db.models" not in imported_modules
    assert "ExecutionOutboxRow" not in text
    assert "update(" not in text
    assert "reconcile_stale_execution_outbox" in text


def test_docker_compose_declares_api_and_worker_topology() -> None:
    compose = (_repo_root() / "apps/backend/docker-compose.yml").read_text(
        encoding="utf-8"
    )

    assert "  api:" in compose
    assert "  worker:" in compose
    assert "celery" in compose
    assert "app.workers.celery_app" in compose
    assert "REDIS_URL: redis://redis:6379/0" in compose


async def _publishing_outbox(
    runtime: ExecutionRuntime,
    *,
    tenant_id: str,
    dispatch_id: str,
    claimed_at: datetime,
):
    request = await runtime.request_diagnostic_execution(
        dispatch_id=dispatch_id,
        session_id=f"session-{dispatch_id}",
        tenant_id=tenant_id,
        requested_at=_BASE - timedelta(hours=1),
        admission_token=execution_admission_token(
            tenant_id=tenant_id,
            admitted_at=_BASE - timedelta(hours=1),
        ),
    )
    claim = await runtime.claim_outbox_for_execution(
        execution_id=request.execution.execution_id,
        publisher_id=f"publisher-{tenant_id}",
        claimed_at=claimed_at,
    )
    assert claim.outbox is not None
    return claim.outbox


def _observability_runtime() -> OperationalObservabilityRuntime:
    return OperationalObservabilityRuntime(
        persistence=InMemoryOperationalObservabilityPersistence(
            boundary_ingress_records=(
                _ingress(1, tenant_id="tenant-a", failed=True),
                _ingress(2, tenant_id="tenant-a", failed=False),
                _ingress(3, tenant_id="tenant-b", failed=True),
            ),
            execution_records=(
                _execution(1, tenant_id="tenant-a", claimed_minutes_ago=30),
                _execution(2, tenant_id="tenant-a", claimed_minutes_ago=1),
                _execution(3, tenant_id="tenant-b", claimed_minutes_ago=30),
            ),
        )
    )


def _execution(
    index: int,
    *,
    tenant_id: str,
    claimed_minutes_ago: int,
) -> ExecutionRecord:
    return ExecutionRecord(
        execution_id=ExecutionId(_uuid(1000 + index)),
        kind=ExecutionKind.DIAGNOSTIC_AGENT,
        dispatch_id=f"dispatch-{index}",
        session_id=f"session-{index}",
        tenant_id=tenant_id,
        state=ExecutionState.CLAIMED,
        attempt_count=1,
        requested_at=_BASE - timedelta(minutes=claimed_minutes_ago + 5),
        claimed_at=_BASE - timedelta(minutes=claimed_minutes_ago),
        worker_id=f"worker-{index}",
    )


def _ingress(
    index: int,
    *,
    tenant_id: str,
    failed: bool,
) -> BoundaryIngressRecord:
    status = (
        BoundaryNormalizationStatus.MALFORMED
        if failed
        else BoundaryNormalizationStatus.OK
    )
    return BoundaryIngressRecord(
        ingress_id=BoundaryIngressId(_uuid(2000 + index)),
        direction=BoundaryDirection.INGRESS,
        runtime_instance_id=_uuid(3000),
        sequence=index,
        source_type=BoundarySourceType.EMAIL,
        source_id=f"source-{index}",
        tenant_id=tenant_id,
        adapter_name="email",
        normalization_status=status,
        message_type=BoundaryMessageType.MESSAGE_RECEIVED,
        replay_disposition=BoundaryReplayDisposition.INVALID_KEY,
        replay_key=None,
        event_id=None,
        original_event_id=None,
        external_message_id=f"external-{index}" if not failed else None,
        external_conversation_id=f"conversation-{index}",
        external_emitted_at=None,
        received_at=_BASE - timedelta(minutes=index),
        started_at=_BASE - timedelta(minutes=index),
        ended_at=_BASE - timedelta(minutes=index) + timedelta(milliseconds=1),
        latency_ms=1.0,
        correlation_id=f"corr-{index}",
        request_id=f"req-{index}",
        canonical_payload={} if failed else {"body": "ok"},
        error="missing body" if failed else None,
        metadata={"channel": "email"},
    )


def _uuid(value: int) -> uuid.UUID:
    return uuid.UUID(f"00000000-0000-0000-0000-{value:012d}")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]
