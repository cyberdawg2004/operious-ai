"""PR_T5 batch-safe boundary ingestion tests."""

from __future__ import annotations

import inspect
import time
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.ingress import (
    BatchIngestItem,
    BatchIngestRequest,
    BatchItemStatus,
)
from app.boundary.db.models import BoundaryIngressRow
from app.boundary.identity import (
    BoundaryIngressId,
    as_ingress_id,
    make_boundary_id,
)
from app.boundary.persistence import (
    BoundaryIngressRecord,
    PostgresBoundaryPersistence,
)
from app.dependencies.services import (
    check_batch_ingest_admission,
    get_admission_service,
    get_batch_ingest_service,
)
from app.hardening.admission import (
    AdmissionDecision,
    AdmissionOutcome,
    AdmissionReason,
)
from app.main import create_app
from app.services.batch_ingest_service import BatchIngestService
from tests.conftest import requires_postgres

TENANT_ID = "tenant-acme"
OTHER_TENANT_ID = "tenant-other"
RECEIVED_AT = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
RUN_ID = uuid.uuid4().hex


@pytest.fixture
def pg_tenant_id() -> str:
    return TENANT_ID


@pytest.mark.asyncio
@requires_postgres
async def test_batch_ingest_accepts_valid_items(
    pg_session: AsyncSession,
) -> None:
    repo = _CountingPostgresBoundaryPersistence(pg_session)
    dispatch = _RecordingDispatchService()
    service = _service(repo=repo, dispatch=dispatch)
    items = [_item("accept-1"), _item("accept-2", channel_type="whatsapp")]

    response = await service.process_batch(items=items, tenant_id=TENANT_ID)

    assert response.total == 2
    assert response.accepted == 2
    assert response.duplicate == 0
    assert response.rejected == 0
    assert [result.status for result in response.results] == [
        BatchItemStatus.ACCEPTED,
        BatchItemStatus.ACCEPTED,
    ]
    assert repo.existing_id_calls == 1
    assert repo.bulk_insert_calls == 1
    assert len(dispatch.calls) == 2
    for item, result in zip(items, response.results, strict=True):
        assert result.boundary_id == make_boundary_id(
            TENANT_ID,
            item.channel_type,
            item.source_id,
            item.external_message_id,
        )
        record = await repo.get_ingress(
            as_ingress_id(result.boundary_id),
            expected_tenant_id=TENANT_ID,
        )
        assert record is not None
        assert record.external_message_id == item.external_message_id


@pytest.mark.asyncio
@requires_postgres
async def test_batch_ingest_deduplicates_within_batch(
    pg_session: AsyncSession,
) -> None:
    repo = _CountingPostgresBoundaryPersistence(pg_session)
    dispatch = _RecordingDispatchService()
    service = _service(repo=repo, dispatch=dispatch)
    item = _item("within-dup")

    response = await service.process_batch(
        items=[item, item],
        tenant_id=TENANT_ID,
    )

    assert response.accepted == 1
    assert response.duplicate == 1
    assert response.rejected == 0
    assert response.results[0].status is BatchItemStatus.ACCEPTED
    assert response.results[1].status is BatchItemStatus.DUPLICATE
    assert response.results[0].boundary_id == response.results[1].boundary_id
    assert len(dispatch.calls) == 1
    assert await _count_boundary_rows(
        pg_session,
        [response.results[0].boundary_id or ""],
    ) == 1


@pytest.mark.asyncio
@requires_postgres
async def test_batch_ingest_deduplicates_across_batches(
    pg_session: AsyncSession,
) -> None:
    repo = _RaceyPostgresBoundaryPersistence(pg_session)
    dispatch = _RecordingDispatchService()
    service = _service(repo=repo, dispatch=dispatch)
    items = [_item("across-1"), _item("across-2")]

    first = await service.process_batch(items=items, tenant_id=TENANT_ID)
    dispatch.calls.clear()
    repo.hide_existing_ids = True
    second = await service.process_batch(items=items, tenant_id=TENANT_ID)

    assert first.accepted == 2
    assert second.accepted == 0
    assert second.duplicate == 2
    assert second.rejected == 0
    assert dispatch.calls == []
    assert repo.bulk_insert_calls == 2
    assert await _count_boundary_rows(
        pg_session,
        [result.boundary_id or "" for result in first.results],
    ) == 2


@pytest.mark.asyncio
@requires_postgres
async def test_1000_item_batch_with_30_percent_duplicates(
    pg_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BATCH_INGEST_MAX_BATCH_SIZE", "1000")
    repo = _CountingPostgresBoundaryPersistence(pg_session)
    dispatch = _RecordingDispatchService()
    service = _service(repo=repo, dispatch=dispatch)
    seed_items = [_item(f"bulk-{index}") for index in range(300)]
    all_items = [_item(f"bulk-{index}") for index in range(1000)]
    BatchIngestRequest(items=all_items)

    await service.process_batch(items=seed_items, tenant_id=TENANT_ID)
    dispatch.calls.clear()
    repo.reset_counts()
    started = time.perf_counter()
    response = await service.process_batch(
        items=all_items,
        tenant_id=TENANT_ID,
    )
    duration = time.perf_counter() - started

    assert response.accepted == 700
    assert response.duplicate == 300
    assert response.rejected == 0
    assert repo.existing_id_calls == 1
    assert repo.bulk_insert_calls == 1
    assert len(dispatch.calls) == 700
    assert duration < 5.0


@pytest.mark.asyncio
@requires_postgres
async def test_batch_rejects_items_with_empty_body(
    pg_session: AsyncSession,
) -> None:
    repo = _CountingPostgresBoundaryPersistence(pg_session)
    dispatch = _RecordingDispatchService()
    service = _service(repo=repo, dispatch=dispatch)
    valid = _item("partial-valid")
    invalid = _item("partial-empty", body="")

    response = await service.process_batch(
        items=[valid, invalid],
        tenant_id=TENANT_ID,
    )

    assert response.accepted == 1
    assert response.duplicate == 0
    assert response.rejected == 1
    assert response.results[1].status is BatchItemStatus.REJECTED
    assert response.results[1].reason == "body must not be empty"
    assert len(dispatch.calls) == 1
    assert await _count_boundary_rows(
        pg_session,
        [
            make_boundary_id(
                TENANT_ID,
                "email",
                valid.source_id,
                valid.external_message_id,
            )
        ],
    ) == 1
    assert await _count_boundary_rows(
        pg_session,
        [
            make_boundary_id(
                TENANT_ID,
                "email",
                invalid.source_id,
                invalid.external_message_id,
            )
        ],
    ) == 0


@pytest.mark.asyncio
@requires_postgres
async def test_batch_cannot_inject_other_tenant_items(
    pg_session: AsyncSession,
) -> None:
    repo = _CountingPostgresBoundaryPersistence(pg_session)
    dispatch = _RecordingDispatchService()
    service = _service(repo=repo, dispatch=dispatch)
    valid = _item("tenant-valid", tenant_id=TENANT_ID)
    injected = _item("tenant-injected", tenant_id=OTHER_TENANT_ID)

    response = await service.process_batch(
        items=[valid, injected],
        tenant_id=TENANT_ID,
    )

    assert response.accepted == 1
    assert response.rejected == 1
    assert response.results[1].status is BatchItemStatus.REJECTED
    assert response.results[1].reason == (
        "tenant_id does not match request authority"
    )
    assert len(dispatch.calls) == 1
    assert await _count_other_tenant_rows(pg_session, "tenant-injected") == 0


@pytest.mark.asyncio
async def test_batch_returns_503_when_admission_defers() -> None:
    app = create_app()
    service = _FailingBatchIngestService()
    app.dependency_overrides[get_admission_service] = lambda: _FakeAdmissionService(
        AdmissionOutcome.DEFER
    )
    app.dependency_overrides[get_batch_ingest_service] = lambda: service

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/ingest/batch",
            json={"items": [_item_payload("admission-defer")]},
            headers={"X-Tenant-ID": TENANT_ID},
        )

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "15"
    assert service.calls == 0


@pytest.mark.asyncio
async def test_batch_rejects_oversized_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BATCH_INGEST_MAX_BATCH_SIZE", "1")
    app = create_app()
    service = _FailingBatchIngestService()
    app.dependency_overrides[check_batch_ingest_admission] = _admitted
    app.dependency_overrides[get_batch_ingest_service] = lambda: service

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/ingest/batch",
            json={
                "items": [
                    _item_payload("oversized-1"),
                    _item_payload("oversized-2"),
                ]
            },
            headers={"X-Tenant-ID": TENANT_ID},
        )

    assert response.status_code == 422
    assert service.calls == 0


def test_boundary_ids_are_deterministic() -> None:
    first = make_boundary_id(
        TENANT_ID,
        "email",
        "support@example.com",
        "deterministic-1",
    )
    second = make_boundary_id(
        TENANT_ID,
        "email",
        "support@example.com",
        "deterministic-1",
    )
    different = make_boundary_id(
        TENANT_ID,
        "email",
        "support@example.com",
        "deterministic-2",
    )

    assert first == second
    assert first != different
    uuid.UUID(first)
    assert "uuid4" not in inspect.getsource(make_boundary_id)


@pytest.mark.asyncio
async def test_batch_rejects_empty_items_list() -> None:
    app = create_app()
    service = _FailingBatchIngestService()
    app.dependency_overrides[check_batch_ingest_admission] = _admitted
    app.dependency_overrides[get_batch_ingest_service] = lambda: service

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        openapi = await client.get("/openapi.json")
        response = await client.post(
            "/api/v1/ingest/batch",
            json={"items": []},
            headers={"X-Tenant-ID": TENANT_ID},
        )

    assert "/api/v1/ingest/batch" in openapi.json()["paths"]
    assert response.status_code == 422
    assert service.calls == 0


def _service(
    *,
    repo: PostgresBoundaryPersistence,
    dispatch: "_RecordingDispatchService",
) -> BatchIngestService:
    return BatchIngestService(
        boundary_repository=repo,
        dispatch_service=dispatch,
    )


def _item(
    external_message_id: str,
    *,
    channel_type: str = "email",
    source_id: str = "support@example.com",
    body: str = "customer needs help",
    tenant_id: str | None = None,
) -> BatchIngestItem:
    return BatchIngestItem(
        channel_type=channel_type,
        source_id=source_id,
        external_message_id=f"{RUN_ID}-{external_message_id}",
        subject="Support request",
        body=body,
        received_at=RECEIVED_AT,
        tenant_id=tenant_id,
        metadata={"test": "batch_ingest"},
    )


def _item_payload(external_message_id: str) -> dict[str, object]:
    return {
        "channel_type": "email",
        "source_id": "support@example.com",
        "external_message_id": external_message_id,
        "subject": "Support request",
        "body": "customer needs help",
        "received_at": RECEIVED_AT.isoformat(),
        "metadata": {"test": "batch_ingest"},
    }


async def _count_boundary_rows(
    session: AsyncSession,
    boundary_ids: list[str],
) -> int:
    ids = [uuid.UUID(boundary_id) for boundary_id in boundary_ids]
    result = await session.execute(
        select(func.count())
        .select_from(BoundaryIngressRow)
        .where(BoundaryIngressRow.ingress_id.in_(ids))
    )
    return int(result.scalar_one())


async def _count_other_tenant_rows(
    session: AsyncSession,
    external_message_id_prefix: str,
) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(BoundaryIngressRow)
        .where(
            BoundaryIngressRow.tenant_id == OTHER_TENANT_ID,
            BoundaryIngressRow.external_message_id.like(
                f"{external_message_id_prefix}-%"
            ),
        )
    )
    return int(result.scalar_one())


async def _admitted() -> AdmissionDecision:
    return _admission_decision(AdmissionOutcome.ADMIT)


def _admission_decision(outcome: AdmissionOutcome) -> AdmissionDecision:
    return AdmissionDecision(
        decision_id=uuid.uuid5(uuid.NAMESPACE_URL, f"batch-test:{outcome.value}"),
        outcome=outcome,
        reason=(
            AdmissionReason.QUEUE_DEPTH_EXCEEDED
            if outcome is not AdmissionOutcome.ADMIT
            else None
        ),
        queue_name="diagnostic.normal",
        queue_depth=100,
        queue_age_seconds=None,
        redis_memory_pct=None,
        db_pool_wait_ms=None,
        retry_after_seconds=15,
        evaluated_at=RECEIVED_AT,
    )


class _RecordingDispatchService:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def dispatch(self, ingress_id: str, tenant_id: str) -> object:
        self.calls.append({"ingress_id": ingress_id, "tenant_id": tenant_id})
        return object()


class _FailingBatchIngestService:
    def __init__(self) -> None:
        self.calls = 0

    async def process_batch(
        self,
        *,
        items: list[BatchIngestItem],
        tenant_id: str,
    ) -> object:
        del items, tenant_id
        self.calls += 1
        raise AssertionError("batch service should not be called")


class _FakeAdmissionService:
    def __init__(self, outcome: AdmissionOutcome) -> None:
        self.outcome = outcome

    async def evaluate_and_persist(
        self,
        **kwargs: object,
    ) -> AdmissionDecision:
        del kwargs
        return _admission_decision(self.outcome)


class _CountingPostgresBoundaryPersistence(PostgresBoundaryPersistence):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.existing_id_calls = 0
        self.bulk_insert_calls = 0

    def reset_counts(self) -> None:
        self.existing_id_calls = 0
        self.bulk_insert_calls = 0

    async def get_existing_ingress_ids(
        self,
        ingress_ids: Sequence[BoundaryIngressId],
        *,
        expected_tenant_id: str,
    ) -> set[BoundaryIngressId]:
        self.existing_id_calls += 1
        return await super().get_existing_ingress_ids(
            ingress_ids,
            expected_tenant_id=expected_tenant_id,
        )

    async def bulk_insert_ingress_records(
        self,
        records: Sequence[BoundaryIngressRecord],
    ) -> set[BoundaryIngressId]:
        self.bulk_insert_calls += 1
        return await super().bulk_insert_ingress_records(records)


class _RaceyPostgresBoundaryPersistence(_CountingPostgresBoundaryPersistence):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.hide_existing_ids = False

    async def get_existing_ingress_ids(
        self,
        ingress_ids: Sequence[BoundaryIngressId],
        *,
        expected_tenant_id: str,
    ) -> set[BoundaryIngressId]:
        if self.hide_existing_ids:
            self.existing_id_calls += 1
            return set()
        return await super().get_existing_ingress_ids(
            ingress_ids,
            expected_tenant_id=expected_tenant_id,
        )
