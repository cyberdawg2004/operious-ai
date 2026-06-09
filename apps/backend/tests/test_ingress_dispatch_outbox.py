"""Durable inbound ingress dispatch outbox coverage."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.boundary.db.models import BoundaryIngressRow, IngressDispatchOutboxRow
from app.boundary.enums import (
    BoundaryDirection,
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.identity import BoundaryIngressId, derive_event_id, derive_replay_key
from app.boundary.ingress_dispatch_outbox import (
    IngressDispatchOutboxQuery,
    IngressDispatchOutboxRuntime,
    IngressDispatchOutboxStatus,
)
from app.boundary.persistence import (
    BoundaryIngressRecord,
    InMemoryBoundaryPersistence,
    PostgresBoundaryPersistence,
)
from scripts.backfill_ingress_dispatch_outbox import (
    backfill_ingress_dispatch_outbox,
)
from tests.conftest import requires_postgres
from app.workers.ingress_dispatch_tasks import process_ingress_dispatch_outbox_runtime

TENANT_ID = "tenant-ingress-dispatch-outbox"
NOW = datetime(2026, 6, 9, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_single_ingress_capture_creates_dispatch_outbox_atomically() -> None:
    store = InMemoryBoundaryPersistence()
    runtime = IngressDispatchOutboxRuntime(persistence=store)
    record = _ingress_record(channel="email", external_message_id="single")

    await store.save_ingress(record)

    outbox = await runtime.get_outbox_by_ingress(record.ingress_id)
    assert outbox is not None
    assert outbox.ingress_id == record.ingress_id
    assert outbox.tenant_id == TENANT_ID
    assert outbox.channel == "email"
    assert outbox.status is IngressDispatchOutboxStatus.PENDING


@pytest.mark.asyncio
async def test_bulk_insert_creates_outbox_for_eligible_new_records_only() -> None:
    store = InMemoryBoundaryPersistence()
    runtime = IngressDispatchOutboxRuntime(persistence=store)
    email = _ingress_record(channel="email", external_message_id="bulk-email")
    whatsapp = _ingress_record(
        channel="whatsapp",
        source_type=BoundarySourceType.WHATSAPP,
        external_message_id="bulk-whatsapp",
    )
    voice = _ingress_record(
        channel="voice",
        source_type=BoundarySourceType.TWILIO_VOICE,
        external_message_id="bulk-voice",
    )

    inserted = await store.bulk_insert_ingress_records((email, whatsapp, voice))

    page = await runtime.list_outbox(IngressDispatchOutboxQuery())
    assert inserted == {email.ingress_id, whatsapp.ingress_id, voice.ingress_id}
    assert page.total == 2
    assert {record.ingress_id for record in page.records} == {
        email.ingress_id,
        whatsapp.ingress_id,
    }


@pytest.mark.asyncio
async def test_duplicate_and_ineligible_ingress_do_not_create_outbox() -> None:
    store = InMemoryBoundaryPersistence()
    runtime = IngressDispatchOutboxRuntime(persistence=store)
    accepted = _ingress_record(channel="email", external_message_id="dedupe")
    duplicate = _ingress_record(channel="email", external_message_id="dedupe")
    failed_auth = _ingress_record(
        channel="email",
        external_message_id="failed-auth",
        normalization_status=BoundaryNormalizationStatus.UNAUTHENTICATED,
    )
    failed_normalization = _ingress_record(
        channel="email",
        external_message_id="failed-normalization",
        normalization_status=BoundaryNormalizationStatus.MALFORMED,
    )
    replay = _ingress_record(
        channel="email",
        external_message_id="replay-known",
        replay_disposition=BoundaryReplayDisposition.REPLAY_OF_KNOWN,
    )
    tenantless = _ingress_record(
        channel="email",
        external_message_id="tenantless",
        tenant_id=None,
    )

    await store.save_ingress(accepted)
    await store.save_ingress(duplicate)
    await store.bulk_insert_ingress_records(
        (failed_auth, failed_normalization, replay, tenantless)
    )

    page = await runtime.list_outbox(IngressDispatchOutboxQuery())
    assert page.total == 1
    assert page.records[0].ingress_id == accepted.ingress_id


@pytest.mark.asyncio
async def test_admission_pressure_after_capture_reschedules_instead_of_dropping() -> (
    None
):
    store = InMemoryBoundaryPersistence()
    runtime = IngressDispatchOutboxRuntime(persistence=store)
    record = _ingress_record(channel="email", external_message_id="pressure")
    await store.save_ingress(record)
    outbox = await runtime.get_outbox_by_ingress(record.ingress_id)
    assert outbox is not None

    result = await process_ingress_dispatch_outbox_runtime(
        outbox_id=str(outbox.outbox_id),
        outbox_runtime=runtime,
        dispatch_service=_RecordingDispatchService(),
        admission_service=_AdmissionService(allowed=False),
        now=NOW,
        worker_id="pytest:ingress-pressure",
    )

    refreshed = await runtime.get_outbox(outbox.outbox_id)
    assert result["status"] == "rescheduled"
    assert refreshed is not None
    assert refreshed.status is IngressDispatchOutboxStatus.PENDING
    assert refreshed.next_attempt_at is not None
    assert refreshed.next_attempt_at > NOW
    assert refreshed.last_error == "ingress dispatch admission deferred"


@pytest.mark.asyncio
async def test_stale_claim_is_requeued_by_reconciler() -> None:
    store = InMemoryBoundaryPersistence()
    runtime = IngressDispatchOutboxRuntime(persistence=store)
    record = _ingress_record(channel="email", external_message_id="stale-claim")
    await store.save_ingress(record)

    claim = await runtime.claim_due_outbox(
        ingress_id=record.ingress_id,
        worker_id="pytest:stale-a",
        claimed_at=NOW,
    )
    assert claim.claimed
    assert claim.outbox is not None

    sweep = await runtime.requeue_stale_claimed(
        stale_before=NOW + timedelta(minutes=10),
        requeued_at=NOW + timedelta(minutes=10),
        limit=100,
        reason="lost claim",
    )

    refreshed = await runtime.get_outbox_by_ingress(record.ingress_id)
    assert sweep.requeued_count == 1
    assert refreshed is not None
    assert refreshed.status is IngressDispatchOutboxStatus.PENDING
    assert refreshed.claim_id is None
    assert refreshed.worker_id is None
    assert refreshed.last_error == "lost claim"


@pytest.mark.asyncio
async def test_exhausted_attempts_dead_letter_instead_of_retrying_forever() -> None:
    store = InMemoryBoundaryPersistence()
    runtime = IngressDispatchOutboxRuntime(persistence=store, max_attempts=1)
    record = _ingress_record(channel="email", external_message_id="dead-letter")
    await store.save_ingress(record)
    outbox = await runtime.get_outbox_by_ingress(record.ingress_id)
    assert outbox is not None

    result = await process_ingress_dispatch_outbox_runtime(
        outbox_id=str(outbox.outbox_id),
        outbox_runtime=runtime,
        dispatch_service=_FailingDispatchService(),
        admission_service=_AdmissionService(allowed=True),
        dead_letter_sink=_RecordingDeadLetterSink(),
        event_sink=_RecordingEventSink(),
        now=NOW,
        worker_id="pytest:ingress-dlq",
    )

    refreshed = await runtime.get_outbox(outbox.outbox_id)
    assert result["status"] == "dead_lettered"
    assert refreshed is not None
    assert refreshed.status is IngressDispatchOutboxStatus.DEAD_LETTERED
    assert refreshed.last_error == "RuntimeError: dispatch transport failed"


@pytest.mark.asyncio
async def test_double_dispatch_attempt_converges_to_one_claim() -> None:
    store = InMemoryBoundaryPersistence()
    runtime = IngressDispatchOutboxRuntime(persistence=store)
    dispatch = _RecordingDispatchService()
    record = _ingress_record(channel="email", external_message_id="double")
    await store.save_ingress(record)
    outbox = await runtime.get_outbox_by_ingress(record.ingress_id)
    assert outbox is not None

    first = await process_ingress_dispatch_outbox_runtime(
        outbox_id=str(outbox.outbox_id),
        outbox_runtime=runtime,
        dispatch_service=dispatch,
        admission_service=_AdmissionService(allowed=True),
        now=NOW,
        worker_id="pytest:double-a",
    )
    second = await process_ingress_dispatch_outbox_runtime(
        outbox_id=str(outbox.outbox_id),
        outbox_runtime=runtime,
        dispatch_service=dispatch,
        admission_service=_AdmissionService(allowed=True),
        now=NOW,
        worker_id="pytest:double-b",
    )

    assert first["status"] == "dispatched"
    assert second["status"] == "not_claimed"
    assert dispatch.calls == [(str(record.ingress_id), TENANT_ID)]


@pytest.mark.asyncio
@requires_postgres
async def test_postgres_ingress_delete_cascades_outbox_for_tenant_cleanup(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresBoundaryPersistence(pg_session)
    record = _ingress_record(channel="email", external_message_id="cascade-cleanup")
    await repo.save_ingress(record)
    await pg_session.flush()
    assert await _postgres_outbox_count(pg_session, record.ingress_id) == 1

    await pg_session.execute(
        delete(BoundaryIngressRow).where(
            BoundaryIngressRow.ingress_id == record.ingress_id
        )
    )
    await pg_session.flush()

    assert await _postgres_outbox_count(pg_session, record.ingress_id) == 0


@pytest.mark.asyncio
@requires_postgres
async def test_postgres_save_ingress_rolls_back_when_outbox_insert_fails(
    pg_session: AsyncSession,
) -> None:
    repo = _OutboxFailingPostgresBoundaryPersistence(pg_session)
    record = _ingress_record(channel="email", external_message_id="atomic-single")

    with pytest.raises(RuntimeError, match="forced outbox failure"):
        await repo.save_ingress(record)
    await pg_session.rollback()

    persisted = await PostgresBoundaryPersistence(pg_session).get_ingress(
        record.ingress_id,
        expected_tenant_id=TENANT_ID,
    )
    assert persisted is None


@pytest.mark.asyncio
@requires_postgres
async def test_postgres_bulk_insert_rolls_back_when_outbox_insert_fails(
    pg_session: AsyncSession,
) -> None:
    repo = _OutboxFailingPostgresBoundaryPersistence(pg_session)
    record = _ingress_record(channel="email", external_message_id="atomic-bulk")

    with pytest.raises(RuntimeError, match="forced outbox failure"):
        await repo.bulk_insert_ingress_records((record,))
    await pg_session.rollback()

    persisted = await PostgresBoundaryPersistence(pg_session).get_ingress(
        record.ingress_id,
        expected_tenant_id=TENANT_ID,
    )
    assert persisted is None


@pytest.mark.asyncio
@requires_postgres
async def test_backfill_dry_run_changes_nothing(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresBoundaryPersistence(pg_session)
    record = _ingress_record(channel="email", external_message_id="backfill-dry")
    await repo.save_ingress(record)
    await pg_session.execute(
        delete(IngressDispatchOutboxRow).where(
            IngressDispatchOutboxRow.ingress_id == record.ingress_id
        )
    )

    result = await backfill_ingress_dispatch_outbox(
        session=pg_session,
        tenant_id=TENANT_ID,
        since=NOW - timedelta(days=1),
        limit=100,
        apply=False,
    )

    assert result.dry_run is True
    assert result.eligible == 1
    assert await _postgres_outbox_count(pg_session, record.ingress_id) == 0


@pytest.mark.asyncio
@requires_postgres
async def test_backfill_apply_creates_one_pending_intent_idempotently(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresBoundaryPersistence(pg_session)
    record = _ingress_record(channel="email", external_message_id="backfill-apply")
    await repo.save_ingress(record)
    await pg_session.execute(
        delete(IngressDispatchOutboxRow).where(
            IngressDispatchOutboxRow.ingress_id == record.ingress_id
        )
    )

    first = await backfill_ingress_dispatch_outbox(
        session=pg_session,
        tenant_id=TENANT_ID,
        since=NOW - timedelta(days=1),
        limit=100,
        apply=True,
    )
    second = await backfill_ingress_dispatch_outbox(
        session=pg_session,
        tenant_id=TENANT_ID,
        since=NOW - timedelta(days=1),
        limit=100,
        apply=True,
    )

    assert first.inserted == 1
    assert second.inserted == 0
    assert await _postgres_outbox_count(pg_session, record.ingress_id) == 1


def _ingress_record(
    *,
    channel: str,
    external_message_id: str,
    source_type: BoundarySourceType = BoundarySourceType.EMAIL,
    normalization_status: BoundaryNormalizationStatus = BoundaryNormalizationStatus.OK,
    replay_disposition: BoundaryReplayDisposition = BoundaryReplayDisposition.NEW,
    tenant_id: str | None = TENANT_ID,
) -> BoundaryIngressRecord:
    replay_key = (
        derive_replay_key(
            source_type=source_type.value,
            external_message_id=external_message_id,
            tenant_id=tenant_id or "tenantless",
        )
        if normalization_status is BoundaryNormalizationStatus.OK
        else None
    )
    event_id = (
        derive_event_id(
            source_type=source_type.value,
            external_message_id=external_message_id,
            tenant_id=tenant_id or "tenantless",
        )
        if normalization_status is BoundaryNormalizationStatus.OK
        else None
    )
    return BoundaryIngressRecord(
        ingress_id=BoundaryIngressId(
            uuid.uuid5(uuid.NAMESPACE_URL, external_message_id)
        ),
        direction=BoundaryDirection.INGRESS,
        runtime_instance_id=uuid.UUID("00000000-0000-4000-8000-000000000111"),
        sequence=1,
        source_type=source_type,
        source_id=f"source:{channel}",
        tenant_id=tenant_id,
        adapter_name="pytest-adapter",
        normalization_status=normalization_status,
        message_type=BoundaryMessageType.MESSAGE_RECEIVED,
        replay_disposition=replay_disposition,
        replay_key=replay_key,
        event_id=event_id,
        original_event_id=event_id,
        external_message_id=external_message_id,
        external_conversation_id=external_message_id,
        external_emitted_at=None,
        received_at=NOW,
        started_at=NOW,
        ended_at=NOW,
        latency_ms=1.0,
        correlation_id=external_message_id,
        request_id=external_message_id,
        canonical_payload={"body": "hello", "channel_type": channel},
        error=None if normalization_status is BoundaryNormalizationStatus.OK else "bad",
        metadata={"ticket.channel": channel},
    )


@dataclass
class _AdmissionService:
    allowed: bool

    async def evaluate_and_persist(self, **_: Any) -> Any:
        return _AdmissionDecision(allowed=self.allowed)


@dataclass
class _AdmissionDecision:
    allowed: bool
    decision_id: uuid.UUID = uuid.uuid5(uuid.NAMESPACE_URL, "admission")
    retry_after_seconds: int | None = 30


class _RecordingDispatchService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def dispatch(self, ingress_id: str, tenant_id: str) -> object:
        self.calls.append((ingress_id, tenant_id))
        return object()


class _FailingDispatchService:
    async def dispatch(self, ingress_id: str, tenant_id: str) -> object:
        del ingress_id, tenant_id
        raise RuntimeError("dispatch transport failed")


class _RecordingDeadLetterSink:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    async def record(self, **kwargs: object) -> None:
        self.records.append(dict(kwargs))


class _RecordingEventSink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def emit(self, **kwargs: object) -> None:
        self.events.append(dict(kwargs))


class _OutboxFailingPostgresBoundaryPersistence(PostgresBoundaryPersistence):
    def _ingress_dispatch_outbox(self) -> Any:
        return _FailingOutboxPersistence()


class _FailingOutboxPersistence:
    async def create_outbox_for_ingress(self, *args: Any, **kwargs: Any) -> object:
        del args, kwargs
        raise RuntimeError("forced outbox failure")

    async def bulk_create_outbox_for_ingress(self, *args: Any, **kwargs: Any) -> object:
        del args, kwargs
        raise RuntimeError("forced outbox failure")


async def _postgres_outbox_count(
    session: AsyncSession,
    ingress_id: BoundaryIngressId,
) -> int:
    result = await session.execute(
        select(IngressDispatchOutboxRow).where(
            IngressDispatchOutboxRow.ingress_id == ingress_id
        )
    )
    return len(result.scalars().all())
