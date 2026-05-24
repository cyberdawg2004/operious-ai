"""Worker tenant ContextVar isolation tests."""

from __future__ import annotations

import asyncio

from app.db.tenant_context import get_current_tenant, set_current_tenant


async def test_diagnostic_task_sets_and_clears_tenant_context() -> None:
    set_current_tenant(None)
    assert get_current_tenant() is None

    try:
        set_current_tenant("test-worker-tenant")
        assert get_current_tenant() == "test-worker-tenant"
    finally:
        set_current_tenant(None)

    assert get_current_tenant() is None


async def test_worker_context_does_not_leak_between_tasks() -> None:
    set_current_tenant(None)
    results: dict[str, str | None] = {}

    async def task_a() -> None:
        try:
            set_current_tenant("tenant-a")
            await asyncio.sleep(0)
            results["a"] = get_current_tenant()
        finally:
            set_current_tenant(None)

    async def task_b() -> None:
        await asyncio.sleep(0)
        results["b"] = get_current_tenant()

    await asyncio.gather(task_a(), task_b())

    assert results["a"] == "tenant-a"
    assert results["b"] is None
    assert get_current_tenant() is None
