from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tenant_context import set_current_tenant
from app.workers.agent_tasks import execute_diagnostic_agent_runtime
from tests.conftest import requires_postgres, set_pg_rls_tenant


@requires_postgres
@pytest.mark.asyncio
@pytest.mark.load
async def test_burst_100_all_complete(
    committed_burst_seed,
    suppress_supervisor_enqueue,
    suppress_semantic_validation,
    timing_collector,
    pg_session: AsyncSession,
) -> None:
    del suppress_supervisor_enqueue, suppress_semantic_validation

    tenant_id = "burst-100-tenant"
    ticket_count = 100

    await committed_burst_seed["seed_tenant"](tenant_id)
    execution_ids = [
        await committed_burst_seed["seed_execution"](tenant_id)
        for _ in range(ticket_count)
    ]

    async def run_one(execution_id: str) -> dict[str, Any]:
        set_current_tenant(tenant_id)
        start = time.monotonic()
        result = await execute_diagnostic_agent_runtime(
            execution_id=execution_id,
            tenant_id=tenant_id,
        )
        duration_ms = (time.monotonic() - start) * 1000
        return {"result": result, "duration_ms": duration_ms}

    gathered = await asyncio.gather(
        *[run_one(execution_id) for execution_id in execution_ids],
        return_exceptions=True,
    )

    exceptions = [
        item for item in gathered if isinstance(item, BaseException)
    ]
    assert exceptions == [], (
        "Burst 100 produced runtime exceptions: "
        f"{[(type(exc).__name__, str(exc)) for exc in exceptions]}"
    )

    result_items = [
        item for item in gathered if not isinstance(item, BaseException)
    ]
    assert len(result_items) == ticket_count, (
        f"Expected {ticket_count} runtime result payloads, "
        f"got {len(result_items)}"
    )

    for item in result_items:
        timing_collector.record(float(item["duration_ms"]))

    runtime_results = [item["result"] for item in result_items]
    dead_lettered = [
        result
        for result in runtime_results
        if isinstance(result, dict) and result.get("status") == "dead_lettered"
    ]
    assert dead_lettered == [], (
        "Expected zero dead_lettered runtime results, "
        f"got {len(dead_lettered)}: {dead_lettered[:3]}"
    )

    completed = [
        result
        for result in runtime_results
        if isinstance(result, dict) and result.get("status") == "completed"
    ]
    assert len(completed) == ticket_count, (
        f"Expected {ticket_count} completed executions, "
        f"got {len(completed)}. Results: {runtime_results[:3]}"
    )
    for result in runtime_results:
        assert result["status"] == "completed"

    assert timing_collector.p95() < 30_000, (
        f"P95 completion time {timing_collector.p95():.0f}ms "
        "exceeds 30,000ms SLO"
    )

    await set_pg_rls_tenant(pg_session, "burst-100-isolation-tenant")
    visible_sessions = await pg_session.execute(
        text("SELECT COUNT(*) FROM operational_sessions")
    )
    visible_executions = await pg_session.execute(
        text("SELECT COUNT(*) FROM execution_records")
    )
    session_count = visible_sessions.scalar_one()
    execution_count = visible_executions.scalar_one()
    assert session_count == 0, (
        "Expected isolation tenant to see zero operational_sessions, "
        f"got {session_count}"
    )
    assert execution_count == 0, (
        "Expected isolation tenant to see zero execution_records, "
        f"got {execution_count}"
    )

    print(
        "Burst 100 timing summary: "
        f"p95={timing_collector.p95():.0f}ms, "
        f"p99={timing_collector.p99():.0f}ms, "
        f"max={timing_collector.max():.0f}ms"
    )
