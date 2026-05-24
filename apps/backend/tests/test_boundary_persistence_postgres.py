"""PR-B7 Postgres integration tests for ``PostgresBoundaryPersistence``.

Gated by ``requires_postgres``. Pins write-once on each direction,
tenant-scoped reads on both, canonical ordering parity with the
in-memory backend.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from app.boundary.db.models import BoundaryIngressRow
from app.boundary.enums import (
    BoundaryDirection,
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.exceptions import BoundaryPersistenceError
from app.boundary.identity import (
    BoundaryEgressId,
    BoundaryEventId,
    BoundaryIngressId,
    derive_event_id,
    derive_replay_key,
)
from app.boundary.persistence import (
    BoundaryEgressQuery,
    BoundaryEgressRecord,
    BoundaryIngressQuery,
    BoundaryIngressRecord,
    PostgresBoundaryPersistence,
)
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]


@pytest.fixture
def pg_tenant_id() -> str:
    return "tenant-acme"


def _at(s: int = 0) -> datetime:
    return datetime(2026, 5, 19, 9, 0, s, tzinfo=timezone.utc)


def _ingress(
    *,
    ingress_id: BoundaryIngressId | None = None,
    runtime: uuid.UUID | None = None,
    sequence: int = 0,
    tenant_id: str | None = "tenant-acme",
    external_message_id: str = "ext-1",
    replay_key: uuid.UUID | None = None,
    event_id: BoundaryEventId | None = None,
) -> BoundaryIngressRecord:
    return BoundaryIngressRecord(
        ingress_id=ingress_id or BoundaryIngressId(uuid.uuid4()),
        direction=BoundaryDirection.INGRESS,
        runtime_instance_id=runtime or uuid.uuid4(),
        sequence=sequence,
        source_type=BoundarySourceType.GENERIC,
        source_id="adapter-a",
        tenant_id=tenant_id,
        adapter_name="test-adapter",
        normalization_status=BoundaryNormalizationStatus.OK,
        message_type=BoundaryMessageType.MESSAGE_RECEIVED,
        replay_disposition=BoundaryReplayDisposition.NEW,
        replay_key=replay_key,
        event_id=event_id,
        original_event_id=event_id,
        external_message_id=external_message_id,
        external_conversation_id=None,
        external_emitted_at=None,
        received_at=_at(),
        started_at=_at(sequence),
        ended_at=_at(sequence),
        latency_ms=0.5,
        correlation_id=None,
        request_id=None,
        canonical_payload={"text": "hello"},
        error=None,
    )


def _egress(
    *,
    egress_id: BoundaryEgressId | None = None,
    runtime: uuid.UUID | None = None,
    sequence: int = 0,
    tenant_id: str | None = "tenant-acme",
) -> BoundaryEgressRecord:
    return BoundaryEgressRecord(
        egress_id=egress_id or BoundaryEgressId(uuid.uuid4()),
        direction=BoundaryDirection.EGRESS,
        runtime_instance_id=runtime or uuid.uuid4(),
        sequence=sequence,
        source_type=BoundarySourceType.GENERIC,
        source_id="adapter-a",
        tenant_id=tenant_id,
        adapter_name="test-adapter",
        payload_body={"reply": "ack"},
        payload_content_type="application/json",
        payload_target_uri="https://example.invalid/callback",
        payload_method="POST",
        payload_headers={"x-trace": "1"},
        translated_at=_at(),
        started_at=_at(sequence),
        ended_at=_at(sequence),
        latency_ms=0.5,
        correlation_id=None,
        request_id=None,
        error=None,
    )


# ─── Write + read ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_postgres_saves_and_retrieves_ingress(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresBoundaryPersistence(pg_session)
    record = _ingress()
    await repo.save_ingress(record)

    got = await repo.get_ingress(record.ingress_id)
    assert got is not None
    assert got.ingress_id == record.ingress_id
    assert got.tenant_id == "tenant-acme"
    assert got.canonical_payload == {"text": "hello"}


@pytest.mark.asyncio
async def test_postgres_saves_and_retrieves_egress(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresBoundaryPersistence(pg_session)
    record = _egress()
    await repo.save_egress(record)

    got = await repo.get_egress(record.egress_id)
    assert got is not None
    assert got.egress_id == record.egress_id
    assert got.payload_method == "POST"
    assert got.payload_headers == {"x-trace": "1"}


@pytest.mark.asyncio
async def test_postgres_ingress_write_once(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresBoundaryPersistence(pg_session)
    record = _ingress()
    saved = await repo.save_ingress(record)
    duplicate = await repo.save_ingress(record)

    assert saved.ingress_id == record.ingress_id
    assert duplicate.ingress_id == record.ingress_id


@pytest.mark.asyncio
async def test_postgres_duplicate_replay_key_returns_original(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresBoundaryPersistence(pg_session)
    external_message_id = f"dup-{uuid.uuid4()}"
    replay_key = derive_replay_key(
        source_type=BoundarySourceType.GENERIC.value,
        external_message_id=external_message_id,
        tenant_id="tenant-acme",
    )
    event_id = derive_event_id(
        source_type=BoundarySourceType.GENERIC.value,
        external_message_id=external_message_id,
        tenant_id="tenant-acme",
    )
    original = _ingress(
        external_message_id=external_message_id,
        replay_key=replay_key,
        event_id=event_id,
    )
    duplicate = _ingress(
        external_message_id=external_message_id,
        replay_key=replay_key,
        event_id=event_id,
    )

    await repo.save_ingress(original)
    resolved = await repo.save_ingress(duplicate)

    assert resolved.ingress_id == original.ingress_id
    page = await repo.list_ingress(
        BoundaryIngressQuery(replay_key=replay_key)
    )
    assert page.total == 1


@pytest.mark.asyncio
async def test_postgres_duplicate_event_id_returns_original(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresBoundaryPersistence(pg_session)
    event_id = derive_event_id(
        source_type=BoundarySourceType.GENERIC.value,
        external_message_id=f"event-{uuid.uuid4()}",
        tenant_id="tenant-acme",
    )
    original = _ingress(
        external_message_id="event-original",
        replay_key=uuid.uuid4(),
        event_id=event_id,
    )
    duplicate = _ingress(
        external_message_id="event-duplicate",
        replay_key=uuid.uuid4(),
        event_id=event_id,
    )

    await repo.save_ingress(original)
    resolved = await repo.save_ingress(duplicate)

    assert resolved.ingress_id == original.ingress_id
    page = await repo.list_ingress(
        BoundaryIngressQuery(event_id=event_id)
    )
    assert page.total == 1


@pytest.mark.asyncio
async def test_postgres_concurrent_duplicate_replay_key_resolves_once(
    pg_engine: AsyncEngine,
) -> None:
    external_message_id = f"concurrent-{uuid.uuid4()}"
    replay_key = derive_replay_key(
        source_type=BoundarySourceType.GENERIC.value,
        external_message_id=external_message_id,
        tenant_id="tenant-acme",
    )
    event_id = derive_event_id(
        source_type=BoundarySourceType.GENERIC.value,
        external_message_id=external_message_id,
        tenant_id="tenant-acme",
    )
    first = _ingress(
        external_message_id=external_message_id,
        replay_key=replay_key,
        event_id=event_id,
    )
    second = _ingress(
        external_message_id=external_message_id,
        replay_key=replay_key,
        event_id=event_id,
    )
    session_factory = async_sessionmaker(
        pg_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    async def _save(
        record: BoundaryIngressRecord,
    ) -> BoundaryIngressRecord:
        async with session_factory() as session:
            repo = PostgresBoundaryPersistence(session)
            saved = await repo.save_ingress(record)
            await session.commit()
            return saved

    try:
        saved = await asyncio.gather(_save(first), _save(second))

        assert saved[0].ingress_id == saved[1].ingress_id
        async with session_factory() as session:
            repo = PostgresBoundaryPersistence(session)
            page = await repo.list_ingress(
                BoundaryIngressQuery(replay_key=replay_key)
            )
            assert page.total == 1
            assert page.ingress[0].ingress_id == saved[0].ingress_id
    finally:
        async with pg_engine.begin() as conn:
            await conn.execute(
                delete(BoundaryIngressRow).where(
                    BoundaryIngressRow.replay_key == replay_key
                )
            )


@pytest.mark.asyncio
async def test_postgres_egress_write_once(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresBoundaryPersistence(pg_session)
    record = _egress()
    await repo.save_egress(record)
    with pytest.raises(BoundaryPersistenceError, match="duplicate egress"):
        await repo.save_egress(record)


# ─── Tenant scope ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_postgres_get_ingress_respects_tenant_scope(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresBoundaryPersistence(pg_session)
    record = _ingress(tenant_id="tenant-acme")
    await repo.save_ingress(record)

    assert (
        await repo.get_ingress(
            record.ingress_id, expected_tenant_id="tenant-acme"
        )
        is not None
    )
    assert (
        await repo.get_ingress(
            record.ingress_id, expected_tenant_id="tenant-other"
        )
        is None
    )


@pytest.mark.asyncio
async def test_postgres_get_egress_tenantless_invisible_to_scoped_reader(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresBoundaryPersistence(pg_session)
    record = _egress(tenant_id=None)
    await repo.save_egress(record)

    assert (
        await repo.get_egress(
            record.egress_id, expected_tenant_id="tenant-acme"
        )
        is None
    )
    assert await repo.get_egress(record.egress_id) is not None


@pytest.mark.asyncio
async def test_postgres_list_ingress_clamps_to_tenant(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresBoundaryPersistence(pg_session)
    await repo.save_ingress(_ingress(tenant_id="tenant-acme"))
    await repo.save_ingress(_ingress(tenant_id="tenant-acme"))
    await repo.save_ingress(_ingress(tenant_id="tenant-other"))

    page = await repo.list_ingress(
        BoundaryIngressQuery(), expected_tenant_id="tenant-acme"
    )
    assert page.total == 2
    assert all(r.tenant_id == "tenant-acme" for r in page.ingress)


@pytest.mark.asyncio
async def test_postgres_list_egress_clamps_to_tenant(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresBoundaryPersistence(pg_session)
    await repo.save_egress(_egress(tenant_id="tenant-acme"))
    await repo.save_egress(_egress(tenant_id="tenant-other"))

    page = await repo.list_egress(
        BoundaryEgressQuery(), expected_tenant_id="tenant-acme"
    )
    assert page.total == 1


# ─── Ordering ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_postgres_list_ingress_orders_by_runtime_seq(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresBoundaryPersistence(pg_session)
    runtime = uuid.uuid4()
    await repo.save_ingress(_ingress(runtime=runtime, sequence=2))
    await repo.save_ingress(_ingress(runtime=runtime, sequence=0))
    await repo.save_ingress(_ingress(runtime=runtime, sequence=1))

    page = await repo.list_ingress(BoundaryIngressQuery())
    seqs = [
        r.sequence for r in page.ingress if r.runtime_instance_id == runtime
    ]
    assert seqs == [0, 1, 2]
