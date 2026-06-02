from __future__ import annotations

from collections.abc import AsyncIterator
import math
from typing import Any

from fastapi import Depends
import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.ingress.batch import max_batch_size
from app.db.session import get_owner_session_factory
from app.dependencies.database import get_db_session
from app.dependencies.services import (
    get_admission_service,
    get_dispatch_service,
)
from tests.conftest import requires_postgres, set_pg_rls_tenant


@requires_postgres
@pytest.mark.asyncio
@pytest.mark.load
@pytest.mark.slow
async def test_burst_10000_admission_and_correctness(
    committed_burst_seed,
    suppress_supervisor_enqueue,
    suppress_semantic_validation,
    pg_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del suppress_supervisor_enqueue, suppress_semantic_validation

    tenant_id = "burst-10000-tenant"
    batch_size = 10_000
    max_items_per_call = max_batch_size()
    batch_count = math.ceil(batch_size / max_items_per_call)
    calls = {"count": 0}

    class UnexpectedAdmissionService:
        async def evaluate_and_persist(self, **kwargs: Any) -> None:
            del kwargs
            calls["count"] += 1
            raise AssertionError("batch ingest must not pre-admit before capture")

    class NoOpDispatchService:
        async def dispatch(self, ingress_id: str, tenant_id: str) -> None:
            del ingress_id, tenant_id

    async def get_noop_dispatch_service(
        session: AsyncSession = Depends(get_db_session),
    ) -> AsyncIterator[NoOpDispatchService]:
        try:
            yield NoOpDispatchService()
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    await committed_burst_seed["seed_tenant"](tenant_id)

    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_dispatch_service] = get_noop_dispatch_service
    app.dependency_overrides[get_admission_service] = UnexpectedAdmissionService

    items = [_batch_item(index) for index in range(batch_size)]
    total_accepted = 0
    total_duplicate = 0
    total_rejected = 0

    print(
        "Burst 10000 batching: "
        f"MAX_BATCH_SIZE={max_items_per_call}, "
        f"batch_calls={batch_count}"
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        for batch_index in range(batch_count):
            start = batch_index * max_items_per_call
            end = min(start + max_items_per_call, batch_size)
            response = await client.post(
                "/api/v1/ingest/batch",
                json={"items": items[start:end]},
                headers={"X-Tenant-ID": tenant_id},
            )

            assert response.status_code == 200, response.text
            payload = response.json()
            total_accepted += int(payload["accepted"])
            total_duplicate += int(payload["duplicate"])
            total_rejected += int(payload["rejected"])
            assert payload["accepted"] == end - start
            assert payload["duplicate"] == 0
            assert payload["rejected"] == 0
            assert all(item["status"] == "ACCEPTED" for item in payload["results"])

    assert calls["count"] == 0, (
        "Batch ingest invoked pre-capture admission instead of preserving capture."
    )
    assert total_accepted == batch_size
    assert total_duplicate == 0
    assert total_rejected == 0

    print(
        "Burst 10000 capture totals: "
        f"accepted={total_accepted}, "
        f"duplicate={total_duplicate}, "
        f"rejected={total_rejected}"
    )

    async with get_owner_session_factory()() as session:
        boundary_records = await session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM boundary_ingress
                WHERE tenant_id = :tenant_id
                  AND external_message_id LIKE 'burst-10000-item-%'
                """
            ),
            {"tenant_id": tenant_id},
        )
        boundary_count = boundary_records.scalar_one()
        tail_records = await session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM boundary_ingress
                WHERE tenant_id = :tenant_id
                  AND external_message_id >= 'burst-10000-item-00500'
                  AND external_message_id <= 'burst-10000-item-09999'
                """
            ),
            {"tenant_id": tenant_id},
        )
        tail_record_count = tail_records.scalar_one()

    assert boundary_count == total_accepted, (
        f"DB has {boundary_count} boundary records but "
        f"{total_accepted} items were admitted."
    )
    assert tail_record_count == batch_size - max_items_per_call, (
        "Post-first-batch valid items were not durably captured: "
        f"{tail_record_count}"
    )

    await pg_session.execute(text("SET LOCAL ROLE operious_app_test"))
    await set_pg_rls_tenant(pg_session, "burst-10000-isolation-tenant")
    visible_boundary = await pg_session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM boundary_ingress
            WHERE external_message_id LIKE 'burst-10000-item-%'
            """
        )
    )
    assert visible_boundary.scalar_one() == 0, (
        "Isolation tenant can see burst-10000 boundary_ingress rows. "
        "RLS failed."
    )


def _batch_item(index: int) -> dict[str, object]:
    return {
        "channel_type": "email",
        "source_id": "burst-10000-source",
        "external_message_id": f"burst-10000-item-{index:05d}",
        "subject": "Burst ticket",
        "body": f"Customer ticket {index} reports charging failure.",
        "received_at": "2026-05-25T12:00:00+00:00",
        "metadata": {"origin": "burst_10000", "index": index},
    }
