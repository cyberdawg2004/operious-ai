"""`InMemoryBoundaryPersistence` discipline tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

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
    derive_event_id,
    derive_replay_key,
    generate_egress_id,
    generate_ingress_id,
)
from app.boundary.persistence.memory import (
    InMemoryBoundaryPersistence,
)
from app.boundary.persistence.models import (
    BoundaryEgressQuery,
    BoundaryIngressQuery,
)
from app.boundary.persistence.records import (
    BoundaryEgressRecord,
    BoundaryIngressRecord,
)


def _ingress_record(
    *,
    ingress_id: BoundaryIngressId | None = None,
    sequence: int = 1,
) -> BoundaryIngressRecord:
    coords = {
        "source_type": "zendesk",
        "external_message_id": "evt-1",
        "tenant_id": "t1",
    }
    return BoundaryIngressRecord(
        ingress_id=ingress_id or generate_ingress_id(),
        direction=BoundaryDirection.INGRESS,
        runtime_instance_id=__import__("uuid").uuid4(),
        sequence=sequence,
        source_type=BoundarySourceType.ZENDESK,
        source_id="acct-1",
        tenant_id="t1",
        adapter_name="adapter",
        normalization_status=BoundaryNormalizationStatus.OK,
        message_type=BoundaryMessageType.EVENT_CREATED,
        replay_disposition=BoundaryReplayDisposition.NEW,
        replay_key=derive_replay_key(**coords),
        event_id=derive_event_id(**coords),
        original_event_id=derive_event_id(**coords),
        external_message_id="evt-1",
        external_conversation_id=None,
        external_emitted_at=None,
        received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ended_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        latency_ms=1.0,
        correlation_id="corr-1",
        request_id="req-1",
        canonical_payload={"a": 1},
        error=None,
    )


def _egress_record(
    *,
    egress_id: BoundaryEgressId | None = None,
    sequence: int = 1,
) -> BoundaryEgressRecord:
    return BoundaryEgressRecord(
        egress_id=egress_id or generate_egress_id(),
        direction=BoundaryDirection.EGRESS,
        runtime_instance_id=__import__("uuid").uuid4(),
        sequence=sequence,
        source_type=BoundarySourceType.GENERIC,
        source_id="acct-1",
        tenant_id="t1",
        adapter_name="adapter",
        payload_body={"hi": 1},
        payload_content_type="application/json",
        payload_target_uri="https://x",
        payload_method="POST",
        payload_headers={},
        translated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ended_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        latency_ms=1.0,
        correlation_id="corr-1",
        request_id="req-1",
        error=None,
    )


@pytest.mark.asyncio
async def test_save_and_get_ingress_round_trip() -> None:
    store = InMemoryBoundaryPersistence()
    record = _ingress_record()
    await store.save_ingress(record)
    fetched = await store.get_ingress(record.ingress_id)
    assert fetched == record


@pytest.mark.asyncio
async def test_duplicate_ingress_save_raises() -> None:
    store = InMemoryBoundaryPersistence()
    record = _ingress_record()
    await store.save_ingress(record)
    with pytest.raises(BoundaryPersistenceError):
        await store.save_ingress(record)


@pytest.mark.asyncio
async def test_save_and_get_egress_round_trip() -> None:
    store = InMemoryBoundaryPersistence()
    record = _egress_record()
    await store.save_egress(record)
    fetched = await store.get_egress(record.egress_id)
    assert fetched == record


@pytest.mark.asyncio
async def test_duplicate_egress_save_raises() -> None:
    store = InMemoryBoundaryPersistence()
    record = _egress_record()
    await store.save_egress(record)
    with pytest.raises(BoundaryPersistenceError):
        await store.save_egress(record)


@pytest.mark.asyncio
async def test_list_ingress_filters_and_paginates() -> None:
    store = InMemoryBoundaryPersistence()
    a = _ingress_record(sequence=1)
    b = _ingress_record(sequence=2)
    c = _ingress_record(sequence=3)
    await store.save_ingress(a)
    await store.save_ingress(b)
    await store.save_ingress(c)
    page = await store.list_ingress(
        BoundaryIngressQuery(limit=2)
    )
    assert page.total == 3
    assert len(page.ingress) == 2


@pytest.mark.asyncio
async def test_list_egress_filters_by_correlation() -> None:
    store = InMemoryBoundaryPersistence()
    await store.save_egress(_egress_record())
    page = await store.list_egress(
        BoundaryEgressQuery(correlation_id="not-matching")
    )
    assert page.total == 0
