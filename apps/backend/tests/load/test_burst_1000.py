from __future__ import annotations

import asyncio
import time
from collections import Counter
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_owner_session_factory
from app.db.tenant_context import set_current_tenant
from app.workers.agent_tasks import execute_diagnostic_agent_runtime
from tests.conftest import requires_postgres, set_pg_rls_tenant


@requires_postgres
@pytest.mark.asyncio
@pytest.mark.load
async def test_burst_1000_multi_tenant_isolation(
    committed_burst_seed,
    suppress_supervisor_enqueue,
    suppress_semantic_validation,
    pg_session: AsyncSession,
) -> None:
    del suppress_supervisor_enqueue, suppress_semantic_validation

    tenants = {
        "burst-1000-tenant-a": 700,
        "burst-1000-tenant-b": 200,
        "burst-1000-tenant-c": 100,
    }
    total = sum(tenants.values())

    seed_start = time.monotonic()
    execution_map: dict[str, list[str]] = {}
    for tenant_id, count in tenants.items():
        await committed_burst_seed["seed_tenant"](tenant_id)
        execution_map[tenant_id] = [
            await committed_burst_seed["seed_execution"](tenant_id)
            for _ in range(count)
        ]
    seed_duration = time.monotonic() - seed_start
    print(f"Seeding 1000 executions took: {seed_duration:.1f}s")
    assert seed_duration <= 90, (
        f"Seeding 1000 executions took {seed_duration:.1f}s, "
        "exceeding the 90s stop threshold. Burst phase not run."
    )

    concurrency_limit = 12
    semaphore = asyncio.Semaphore(concurrency_limit)

    # Production workers use NullPool -- each Celery task gets its own Neon
    # connection with no shared pool contention. In tests, the app session
    # factory uses QueuePool(size=10, overflow=5). The semaphore limits
    # concurrency to within the pool limit, matching the effective parallelism
    # that production workers achieve under similar constraints.
    async def run_one_with_limit(
        execution_id: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        async with semaphore:
            set_current_tenant(tenant_id)
            start = time.monotonic()
            try:
                result = await execute_diagnostic_agent_runtime(
                    execution_id=execution_id,
                    tenant_id=tenant_id,
                )
                duration_ms = (time.monotonic() - start) * 1000
                return {
                    "tenant_id": tenant_id,
                    "execution_id": execution_id,
                    "result": result,
                    "duration_ms": duration_ms,
                    "exc": None,
                }
            except Exception as exc:
                duration_ms = (time.monotonic() - start) * 1000
                return {
                    "tenant_id": tenant_id,
                    "execution_id": execution_id,
                    "result": None,
                    "duration_ms": duration_ms,
                    "exc": exc,
                }

    print(
        f"CONCURRENCY_LIMIT={concurrency_limit}, "
        "effective_parallelism=pool_size+overflow=15"
    )

    burst_start = time.monotonic()
    raw = await asyncio.wait_for(
        asyncio.gather(
            *[
                run_one_with_limit(execution_id, tenant_id)
                for tenant_id, execution_ids in execution_map.items()
                for execution_id in execution_ids
            ]
        ),
        timeout=120,
    )
    burst_duration = time.monotonic() - burst_start
    print(f"Burst 1000 execution took: {burst_duration:.1f}s")

    exceptions = [
        item["exc"] for item in raw if item["exc"] is not None
    ]
    result_items = [
        item for item in raw if item["exc"] is None
    ]
    statuses = Counter(
        item["result"].get("status")
        for item in result_items
        if isinstance(item.get("result"), dict)
    )
    completed = statuses["completed"]
    dead_lettered = statuses["dead_lettered"]
    malformed = len(result_items) - sum(statuses.values())

    print(
        "Burst 1000 result counts: "
        f"completed={completed}, "
        f"dead_lettered={dead_lettered}, "
        f"exceptions={len(exceptions)}, "
        f"malformed={malformed}"
    )

    assert exceptions == [], (
        "Burst 1000 produced runtime exceptions: "
        f"{[(type(exc).__name__, str(exc)) for exc in exceptions[:10]]}"
    )
    assert malformed == 0, (
        "Burst 1000 produced malformed runtime results: "
        f"{[item for item in result_items if not isinstance(item.get('result'), dict)][:3]}"
    )
    assert completed + dead_lettered == total, (
        "Ticket accounting mismatch: "
        f"completed={completed} + dead_lettered={dead_lettered} "
        f"!= total={total}. Silent drops detected."
    )

    dlq_expected_by_tenant: Counter[str] = Counter()
    for item in result_items:
        result = item["result"]
        if result["status"] == "dead_lettered":
            dlq_expected_by_tenant[item["tenant_id"]] += 1

    async with get_owner_session_factory()() as session:
        for tenant_id in tenants:
            dlq_records = await session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM dead_letter_tasks
                    WHERE tenant_id = :tenant_id
                    """
                ),
                {"tenant_id": tenant_id},
            )
            dlq_count = dlq_records.scalar_one()
            assert dlq_count == dlq_expected_by_tenant[tenant_id], (
                f"Tenant {tenant_id} has {dlq_count} DLQ records, "
                f"expected {dlq_expected_by_tenant[tenant_id]} "
                "from dead_lettered runtime results."
            )

    await set_pg_rls_tenant(pg_session, "burst-1000-tenant-a")
    tenant_a_sees_b = await pg_session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM operational_sessions
            WHERE tenant_id = :tenant_id
            """
        ),
        {"tenant_id": "burst-1000-tenant-b"},
    )
    assert tenant_a_sees_b.scalar_one() == 0, (
        "Tenant A can see Tenant B operational_sessions. RLS failed."
    )

    await set_pg_rls_tenant(pg_session, "burst-1000-tenant-b")
    tenant_b_sees_c = await pg_session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM operational_sessions
            WHERE tenant_id = :tenant_id
            """
        ),
        {"tenant_id": "burst-1000-tenant-c"},
    )
    assert tenant_b_sees_c.scalar_one() == 0, (
        "Tenant B can see Tenant C operational_sessions. RLS failed."
    )
