"""Postgres execution persistence integration tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution import (
    ExecutionAttemptQuery,
    ExecutionAttemptState,
    ExecutionRuntime,
    ExecutionQuery,
    ExecutionState,
    OutboxQuery,
)
from app.execution.enums import ExecutionOutboxState
from app.execution.persistence import PostgresExecutionPersistence
from tests.conftest import (
    execution_admission_token,
    requires_postgres,
    set_pg_rls_tenant,
)


_NOW = datetime(2026, 5, 22, 6, tzinfo=timezone.utc)


@pytest.fixture
def pg_tenant_id() -> str:
    return "tenant-acme"


@pytest.mark.asyncio
@requires_postgres
async def test_postgres_request_execution_persists_parent_before_outbox(
    pg_session: AsyncSession,
) -> None:
    runtime = ExecutionRuntime(
        persistence=PostgresExecutionPersistence(pg_session)
    )

    first = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-postgres-fk-order",
        session_id="session-postgres-fk-order",
        tenant_id="tenant-acme",
        requested_at=_NOW,
        admission_token=execution_admission_token(
            tenant_id="tenant-acme",
            admitted_at=_NOW,
        ),
    )
    second = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-postgres-fk-order",
        session_id="session-postgres-fk-order",
        tenant_id="tenant-acme",
        requested_at=_NOW,
        admission_token=execution_admission_token(
            tenant_id="tenant-acme",
            admitted_at=_NOW,
        ),
    )
    executions = await runtime.list_executions(
        ExecutionQuery(tenant_id="tenant-acme"),
        expected_tenant_id="tenant-acme",
    )
    outbox = await runtime.list_outbox(
        OutboxQuery(
            execution_id=first.execution.execution_id,
            state=ExecutionOutboxState.PENDING,
        ),
        expected_tenant_id="tenant-acme",
    )

    assert second.execution == first.execution
    assert executions.total == 1
    assert outbox.total == 1
    assert outbox.records[0].execution_id == first.execution.execution_id


@pytest.mark.asyncio
@requires_postgres
async def test_postgres_completion_after_retry_clears_parent_failure_fields(
    pg_session: AsyncSession,
) -> None:
    runtime = ExecutionRuntime(
        persistence=PostgresExecutionPersistence(pg_session)
    )
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-postgres-clear-prior-failure",
        session_id="session-postgres-clear-prior-failure",
        tenant_id="tenant-acme",
        requested_at=_NOW,
        admission_token=execution_admission_token(
            tenant_id="tenant-acme",
            admitted_at=_NOW,
        ),
    )
    first = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-a",
        claimed_at=_NOW + timedelta(seconds=1),
    )
    assert first.attempt is not None
    failed_at = _NOW + timedelta(seconds=2)
    failed = await runtime.fail_execution(
        execution_id=request.execution.execution_id,
        attempt_id=first.attempt.attempt_id,
        worker_id="worker-a",
        error="transient provider failure",
        failed_at=failed_at,
        retry_requested=True,
    )
    assert failed.state is ExecutionState.REQUESTED
    assert failed.error == "transient provider failure"
    assert failed.failed_at == failed_at
    second = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-b",
        claimed_at=_NOW + timedelta(seconds=3),
    )
    assert second.attempt is not None

    completed_at = _NOW + timedelta(seconds=4)
    completed = await runtime.complete_execution(
        execution_id=request.execution.execution_id,
        attempt_id=second.attempt.attempt_id,
        worker_id="worker-b",
        result={"summary": "done"},
        completed_at=completed_at,
    )
    attempts = await runtime.list_attempts(
        ExecutionAttemptQuery(execution_id=request.execution.execution_id),
        expected_tenant_id="tenant-acme",
    )

    assert completed.state is ExecutionState.COMPLETED
    assert completed.completed_at == completed_at
    assert completed.error is None
    assert completed.failed_at is None
    assert attempts.total == 2
    assert attempts.attempts[0].state is ExecutionAttemptState.FAILED
    assert attempts.attempts[0].error == "transient provider failure"
    assert attempts.attempts[0].failed_at == failed_at
    assert attempts.attempts[1].state is ExecutionAttemptState.COMPLETED


@pytest.mark.asyncio
@requires_postgres
async def test_postgres_requeues_stale_outbox_with_tenant_scope(
    pg_session: AsyncSession,
) -> None:
    runtime = ExecutionRuntime(
        persistence=PostgresExecutionPersistence(pg_session)
    )
    own = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-postgres-stale-outbox-own",
        session_id="session-postgres-stale-outbox-own",
        tenant_id="tenant-acme",
        requested_at=_NOW,
        admission_token=execution_admission_token(
            tenant_id="tenant-acme",
            admitted_at=_NOW,
        ),
    )
    await set_pg_rls_tenant(pg_session, "tenant-other")
    other = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-postgres-stale-outbox-other",
        session_id="session-postgres-stale-outbox-other",
        tenant_id="tenant-other",
        requested_at=_NOW,
        admission_token=execution_admission_token(
            tenant_id="tenant-other",
            admitted_at=_NOW,
        ),
    )
    old_claim = _NOW + timedelta(minutes=1)
    await set_pg_rls_tenant(pg_session, "tenant-acme")
    await runtime.claim_outbox_for_execution(
        execution_id=own.execution.execution_id,
        publisher_id="publisher-a",
        claimed_at=old_claim,
    )
    await set_pg_rls_tenant(pg_session, "tenant-other")
    await runtime.claim_outbox_for_execution(
        execution_id=other.execution.execution_id,
        publisher_id="publisher-b",
        claimed_at=old_claim,
    )

    await set_pg_rls_tenant(pg_session, "tenant-acme")
    sweep = await runtime.reconcile_stale_outbox_records(
        stale_before=_NOW + timedelta(minutes=5),
        requeued_at=_NOW + timedelta(minutes=10),
        tenant_id="tenant-acme",
        reason="postgres publisher lease expired",
    )
    own_outbox = await runtime.list_outbox(
        OutboxQuery(tenant_id="tenant-acme"),
        expected_tenant_id="tenant-acme",
    )
    await set_pg_rls_tenant(pg_session, "tenant-other")
    other_outbox = await runtime.list_outbox(
        OutboxQuery(tenant_id="tenant-other"),
        expected_tenant_id="tenant-other",
    )

    assert sweep.reconciled_count == 1
    assert own_outbox.total == 1
    assert own_outbox.records[0].state is ExecutionOutboxState.PENDING
    assert own_outbox.records[0].claimed_at is None
    assert own_outbox.records[0].last_error == "postgres publisher lease expired"
    assert other_outbox.total == 1
    assert other_outbox.records[0].state is ExecutionOutboxState.PUBLISHING


@pytest.mark.asyncio
@requires_postgres
async def test_postgres_requeues_failed_outbox_with_tenant_scope(
    pg_session: AsyncSession,
) -> None:
    runtime = ExecutionRuntime(
        persistence=PostgresExecutionPersistence(pg_session)
    )
    own = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-postgres-failed-outbox-own",
        session_id="session-postgres-failed-outbox-own",
        tenant_id="tenant-acme",
        requested_at=_NOW,
        admission_token=execution_admission_token(
            tenant_id="tenant-acme",
            admitted_at=_NOW,
        ),
    )
    await set_pg_rls_tenant(pg_session, "tenant-other")
    other = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-postgres-failed-outbox-other",
        session_id="session-postgres-failed-outbox-other",
        tenant_id="tenant-other",
        requested_at=_NOW,
        admission_token=execution_admission_token(
            tenant_id="tenant-other",
            admitted_at=_NOW,
        ),
    )
    failed_at = _NOW + timedelta(minutes=1)
    await set_pg_rls_tenant(pg_session, "tenant-acme")
    own_claim = await runtime.claim_outbox_for_execution(
        execution_id=own.execution.execution_id,
        publisher_id="publisher-a",
        claimed_at=failed_at - timedelta(seconds=1),
    )
    assert own_claim.outbox is not None
    assert own_claim.outbox.claim_id is not None
    await runtime.mark_outbox_failed(
        outbox_id=own_claim.outbox.outbox_id,
        claim_id=own_claim.outbox.claim_id,
        error="broker unavailable",
        failed_at=failed_at,
    )
    await set_pg_rls_tenant(pg_session, "tenant-other")
    other_claim = await runtime.claim_outbox_for_execution(
        execution_id=other.execution.execution_id,
        publisher_id="publisher-b",
        claimed_at=failed_at - timedelta(seconds=1),
    )
    assert other_claim.outbox is not None
    assert other_claim.outbox.claim_id is not None
    await runtime.mark_outbox_failed(
        outbox_id=other_claim.outbox.outbox_id,
        claim_id=other_claim.outbox.claim_id,
        error="other broker unavailable",
        failed_at=failed_at,
    )

    await set_pg_rls_tenant(pg_session, "tenant-acme")
    sweep = await runtime.reconcile_failed_execution_outbox_records(
        failed_before_or_at=_NOW + timedelta(minutes=5),
        requeued_at=_NOW + timedelta(minutes=10),
        tenant_id="tenant-acme",
        reason="postgres failed publisher retry",
        max_publish_attempts=3,
    )
    own_outbox = await runtime.list_outbox(
        OutboxQuery(tenant_id="tenant-acme"),
        expected_tenant_id="tenant-acme",
    )
    await set_pg_rls_tenant(pg_session, "tenant-other")
    other_outbox = await runtime.list_outbox(
        OutboxQuery(tenant_id="tenant-other"),
        expected_tenant_id="tenant-other",
    )

    assert sweep.reconciled_count == 1
    assert own_outbox.total == 1
    assert own_outbox.records[0].state is ExecutionOutboxState.PENDING
    assert own_outbox.records[0].claimed_at is None
    assert own_outbox.records[0].publisher_id is None
    assert own_outbox.records[0].last_error == "postgres failed publisher retry"
    assert (
        own_outbox.records[0].metadata[
            "failed_recovery.previous_failure_reason"
        ]
        == "broker unavailable"
    )
    assert (
        own_outbox.records[0].metadata[
            "failed_recovery.retry_attempt_count"
        ]
        == 1
    )
    assert other_outbox.total == 1
    assert other_outbox.records[0].state is ExecutionOutboxState.FAILED
