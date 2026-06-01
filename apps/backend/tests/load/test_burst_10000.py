from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.ingress.batch import max_batch_size
from app.db.session import get_owner_session_factory
from app.dependencies.services import (
    get_admission_service,
    get_execution_publisher,
)
from app.hardening.admission.models import (
    AdmissionDecision,
    AdmissionOutcome,
    AdmissionReason,
)
from app.queues import DIAGNOSTIC_QUEUE_PRIORITY
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

    class NoOpExecutionPublisher:
        async def publish_execution(
            self,
            execution_id: str,
            *,
            tenant_id: str,
        ) -> None:
            del execution_id, tenant_id

    class LocalAdmissionService:
        async def evaluate_and_persist(self, **kwargs: Any) -> AdmissionDecision:
            del kwargs
            calls["count"] += 1
            if calls["count"] == 1:
                return AdmissionDecision(
                    decision_id=uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"burst-10000-admission-admit:{tenant_id}",
                    ),
                    outcome=AdmissionOutcome.ADMIT,
                    reason=None,
                    queue_name=",".join(DIAGNOSTIC_QUEUE_PRIORITY),
                    queue_depth=0,
                    queue_age_seconds=0.0,
                    redis_memory_pct=0.0,
                    db_pool_wait_ms=0.0,
                    retry_after_seconds=0,
                    evaluated_at=datetime.now(timezone.utc),
                )
            return AdmissionDecision(
                decision_id=uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    "burst-10000-admission-defer:"
                    f"{tenant_id}:{calls['count']}",
                ),
                outcome=AdmissionOutcome.DEFER,
                reason=AdmissionReason.QUEUE_DEPTH_EXCEEDED,
                queue_name=",".join(DIAGNOSTIC_QUEUE_PRIORITY),
                queue_depth=2_500,
                queue_age_seconds=None,
                redis_memory_pct=None,
                db_pool_wait_ms=None,
                retry_after_seconds=30,
                evaluated_at=datetime.now(timezone.utc),
            )

    await committed_burst_seed["seed_tenant"](tenant_id)

    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_execution_publisher] = NoOpExecutionPublisher
    app.dependency_overrides[get_admission_service] = LocalAdmissionService

    items = [_batch_item(index) for index in range(batch_size)]
    total_accepted = 0
    total_duplicate = 0
    total_rejected = 0
    deferred_items = 0
    deferred_batches = 0

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

            if batch_index == 0:
                assert response.status_code == 200, response.text
                payload = response.json()
                total_accepted += int(payload["accepted"])
                total_duplicate += int(payload["duplicate"])
                total_rejected += int(payload["rejected"])
                assert payload["accepted"] == max_items_per_call, (
                    "First batch should be fully admitted when queues are empty, "
                    f"got {payload}"
                )
                assert payload["duplicate"] == 0
                assert payload["rejected"] == 0
                assert all(
                    item["status"] == "ACCEPTED"
                    for item in payload["results"]
                )
                continue

            assert response.status_code == 503, response.text
            assert response.headers["Retry-After"] == "30"
            print(f"503 response body: {response.json()!r}")
            detail = response.json()["detail"]
            assert "admission_deferred" in detail
            assert AdmissionReason.QUEUE_DEPTH_EXCEEDED.value in detail
            assert "'retry_after_seconds': 30" in detail
            deferred_batches += 1
            deferred_items += end - start

    assert calls["count"] == batch_count, (
        f"Expected {batch_count} admission evaluations, got {calls['count']}"
    )
    assert total_accepted < batch_size, (
        f"Admission control did not activate: all {batch_size} items accepted."
    )
    assert deferred_batches == batch_count - 1
    assert deferred_items == batch_size - max_items_per_call

    print(
        "Burst 10000 admission totals: "
        f"accepted={total_accepted}, "
        f"duplicate={total_duplicate}, "
        f"rejected={total_rejected}, "
        f"deferred_items={deferred_items}, "
        f"deferred_batches={deferred_batches}"
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
        deferred_records = await session.execute(
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
        deferred_record_count = deferred_records.scalar_one()

    assert boundary_count == total_accepted, (
        f"DB has {boundary_count} boundary records but "
        f"{total_accepted} items were admitted."
    )
    assert deferred_record_count == 0, (
        "Deferred batches left phantom boundary records: "
        f"{deferred_record_count}"
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
