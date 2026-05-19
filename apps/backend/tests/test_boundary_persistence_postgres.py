"""PR-B7 Postgres integration tests for ``PostgresBoundaryPersistence``.

Gated by ``requires_postgres``. Pins write-once on each direction,
tenant-scoped reads on both, canonical ordering parity with the
in-memory backend.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

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
    BoundaryIngressId,
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


def _at(s: int = 0) -> datetime:
    return datetime(2026, 5, 19, 9, 0, s, tzinfo=timezone.utc)


def _ingress(
    *,
    ingress_id: BoundaryIngressId | None = None,
    runtime: uuid.UUID | None = None,
    sequence: int = 0,
    tenant_id: str | None = "tenant-acme",
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
        replay_key=None,
        event_id=None,
        original_event_id=None,
        external_message_id="ext-1",
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
    await repo.save_ingress(record)
    with pytest.raises(BoundaryPersistenceError, match="duplicate ingress"):
        await repo.save_ingress(record)


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
