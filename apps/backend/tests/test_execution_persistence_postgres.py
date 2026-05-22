"""Postgres execution persistence integration tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution import (
    ExecutionRuntime,
    ExecutionQuery,
    OutboxQuery,
)
from app.execution.enums import ExecutionOutboxState
from app.execution.persistence import PostgresExecutionPersistence
from tests.conftest import requires_postgres


_NOW = datetime(2026, 5, 22, 6, tzinfo=timezone.utc)


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
    )
    second = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-postgres-fk-order",
        session_id="session-postgres-fk-order",
        tenant_id="tenant-acme",
        requested_at=_NOW,
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
