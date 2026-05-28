"""Execution CAS and outbox claim-token concurrency tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from app.execution import (
    ExecutionClaimLost,
    ExecutionOutboxClaimLost,
    ExecutionRuntime,
    ExecutionState,
)
from app.execution.enums import ExecutionOutboxState
from app.execution.persistence import PostgresExecutionPersistence
from tests.conftest import execution_admission_token, requires_postgres

pytestmark = [requires_postgres]

_NOW = datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def pg_tenant_id() -> str:
    return f"tenant-exec-cas-{uuid.uuid4()}"


@pytest.mark.asyncio
async def test_complete_execution_matching_attempt_and_worker_succeeds(
    pg_session: AsyncSession,
    pg_tenant_id: str,
) -> None:
    runtime = ExecutionRuntime(
        persistence=PostgresExecutionPersistence(pg_session)
    )
    request = await _request_execution(
        runtime,
        tenant_id=pg_tenant_id,
        seed="normal-complete",
    )
    claim = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-normal",
        claimed_at=_NOW,
    )
    assert claim.attempt is not None

    completed = await runtime.complete_execution(
        execution_id=request.execution.execution_id,
        attempt_id=claim.attempt.attempt_id,
        worker_id="worker-normal",
        result={"summary": "done"},
        completed_at=_NOW + timedelta(seconds=1),
    )

    assert not isinstance(completed, ExecutionClaimLost)
    assert completed.state is ExecutionState.COMPLETED
    assert completed.result == {"summary": "done"}


@pytest.mark.asyncio
async def test_complete_execution_after_recovery_returns_claim_lost(
    pg_engine: AsyncEngine,
) -> None:
    tenant_id = f"tenant-exec-cas-lost-{uuid.uuid4()}"
    seed = "late-complete"
    async with _runtime_for_tenant(pg_engine, tenant_id) as (
        runtime,
        session,
    ):
        request = await _request_execution(
            runtime,
            tenant_id=tenant_id,
            seed=seed,
        )
        claim = await runtime.claim_execution(
            execution_id=request.execution.execution_id,
            worker_id="worker-stale",
            claimed_at=_NOW,
        )
        assert claim.attempt is not None
        stale_attempt_id = claim.attempt.attempt_id
        await session.commit()

    async with _runtime_for_tenant(pg_engine, tenant_id) as (
        runtime,
        session,
    ):
        recovered = await runtime.recover_stale_execution(
            execution_id=request.execution.execution_id,
            stale_before=_NOW + timedelta(minutes=5),
            recovered_at=_NOW + timedelta(minutes=6),
            reason="worker lease expired",
        )
        assert recovered.recovered is True
        await session.commit()

    async with _runtime_for_tenant(pg_engine, tenant_id) as (runtime, _session):
        completed = await runtime.complete_execution(
            execution_id=request.execution.execution_id,
            attempt_id=stale_attempt_id,
            worker_id="worker-stale",
            result={"summary": "too late"},
            completed_at=_NOW + timedelta(minutes=7),
        )
        current = await runtime.get_execution(request.execution.execution_id)
        attempt = await runtime.get_attempt(stale_attempt_id)

    assert isinstance(completed, ExecutionClaimLost)
    assert completed.reason == "execution_not_claimed:requested"
    assert current is not None
    assert current.state is ExecutionState.REQUESTED
    assert current.result == {}
    assert attempt is not None
    assert attempt.state.value == "failed"


@pytest.mark.asyncio
async def test_outbox_mark_published_with_stale_claim_is_noop(
    pg_engine: AsyncEngine,
) -> None:
    tenant_id = f"tenant-outbox-cas-stale-{uuid.uuid4()}"
    seed = "stale-publisher"
    async with _runtime_for_tenant(pg_engine, tenant_id) as (
        runtime,
        session,
    ):
        request = await _request_execution(
            runtime,
            tenant_id=tenant_id,
            seed=seed,
        )
        await session.commit()

    async with _runtime_for_tenant(pg_engine, tenant_id) as (
        runtime,
        session,
    ):
        first = await runtime.claim_outbox_for_execution(
            execution_id=request.execution.execution_id,
            publisher_id="publisher-a",
            claimed_at=_NOW,
        )
        assert first.outbox is not None
        assert first.outbox.claim_id is not None
        stale_claim_id = first.outbox.claim_id
        outbox_id = first.outbox.outbox_id
        await session.commit()

    async with _runtime_for_tenant(pg_engine, tenant_id) as (
        runtime,
        session,
    ):
        reconciled = await runtime.reconcile_stale_outbox(
            outbox_id=outbox_id,
            stale_before=_NOW + timedelta(minutes=5),
            requeued_at=_NOW + timedelta(minutes=6),
            reason="publisher lease expired",
        )
        assert reconciled.reconciled is True
        await session.commit()

    async with _runtime_for_tenant(pg_engine, tenant_id) as (
        runtime,
        session,
    ):
        second = await runtime.claim_outbox_for_execution(
            execution_id=request.execution.execution_id,
            publisher_id="publisher-b",
            claimed_at=_NOW + timedelta(minutes=7),
        )
        assert second.outbox is not None
        assert second.outbox.claim_id is not None
        live_claim_id = second.outbox.claim_id
        assert live_claim_id != stale_claim_id
        await session.commit()

    async with _runtime_for_tenant(pg_engine, tenant_id) as (
        runtime,
        session,
    ):
        stale = await runtime.mark_outbox_published(
            outbox_id=outbox_id,
            claim_id=stale_claim_id,
            published_at=_NOW + timedelta(minutes=8),
        )
        current = await runtime.get_outbox(outbox_id)
        await session.commit()

    assert isinstance(stale, ExecutionOutboxClaimLost)
    assert stale.reason == "outbox_claim_lost"
    assert current is not None
    assert current.state is ExecutionOutboxState.PUBLISHING
    assert current.claim_id == live_claim_id
    assert current.published_at is None


@pytest.mark.asyncio
async def test_outbox_mark_published_with_matching_claim_succeeds(
    pg_session: AsyncSession,
    pg_tenant_id: str,
) -> None:
    runtime = ExecutionRuntime(
        persistence=PostgresExecutionPersistence(pg_session)
    )
    request = await _request_execution(
        runtime,
        tenant_id=pg_tenant_id,
        seed="matching-publisher",
    )
    claim = await runtime.claim_outbox_for_execution(
        execution_id=request.execution.execution_id,
        publisher_id="publisher-ok",
        claimed_at=_NOW,
    )
    assert claim.outbox is not None
    assert claim.outbox.claim_id is not None

    published = await runtime.mark_outbox_published(
        outbox_id=claim.outbox.outbox_id,
        claim_id=claim.outbox.claim_id,
        published_at=_NOW + timedelta(seconds=1),
    )

    assert not isinstance(published, ExecutionOutboxClaimLost)
    assert published.state is ExecutionOutboxState.PUBLISHED
    assert published.claim_id == claim.outbox.claim_id


async def _request_execution(
    runtime: ExecutionRuntime,
    *,
    tenant_id: str,
    seed: str,
):
    return await runtime.request_diagnostic_execution(
        dispatch_id=f"dispatch-{seed}-{uuid.uuid4()}",
        session_id=f"session-{seed}",
        tenant_id=tenant_id,
        requested_at=_NOW,
        admission_token=execution_admission_token(
            tenant_id=tenant_id,
            admitted_at=_NOW,
            seed=seed,
        ),
    )


@asynccontextmanager
async def _runtime_for_tenant(
    engine: AsyncEngine,
    tenant_id: str,
) -> AsyncIterator[tuple[ExecutionRuntime, AsyncSession]]:
    connection: AsyncConnection = await engine.connect()
    await connection.execute(
        text("SELECT set_config('app.current_tenant_id', :t, false)"),
        {"t": tenant_id},
    )
    await connection.commit()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        yield (
            ExecutionRuntime(persistence=PostgresExecutionPersistence(session)),
            session,
        )
    finally:
        await session.close()
        if connection.in_transaction():
            await connection.rollback()
        await connection.close()
