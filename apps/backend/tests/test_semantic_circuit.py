from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.boundary.persistence import InMemoryBoundaryPersistence
from app.semantic import (
    NUM_HASH_FUNCTIONS,
    SemanticCircuitBreaker,
    SemanticCircuitEventRepository,
    SemanticCircuitState,
    TextFingerprinter,
)
from app.services.ticket_ingress_service import TicketIngressService
from tests.conftest import requires_postgres


class _FakeRedis:
    def __init__(self) -> None:
        self.zsets: dict[str, dict[bytes, float]] = {}

    async def zadd(
        self,
        name: str,
        mapping: Mapping[bytes, float],
        *,
        nx: bool = False,
    ) -> int:
        zset = self.zsets.setdefault(name, {})
        added = 0
        for member, score in mapping.items():
            if nx and member in zset:
                continue
            if member not in zset:
                added += 1
            zset[member] = score
        return added

    async def zremrangebyscore(
        self,
        name: str,
        min: int | float,
        max: int | float,
    ) -> int:
        zset = self.zsets.setdefault(name, {})
        removed = [
            member
            for member, score in zset.items()
            if float(min) <= score <= float(max)
        ]
        for member in removed:
            zset.pop(member, None)
        return len(removed)

    async def zrange(
        self,
        name: str,
        start: int,
        end: int,
    ) -> list[bytes]:
        members = [
            member
            for member, _score in sorted(
                self.zsets.setdefault(name, {}).items(),
                key=lambda item: item[1],
            )
        ]
        stop = None if end == -1 else end + 1
        return members[start:stop]


class _FailingRedis(_FakeRedis):
    async def zadd(
        self,
        name: str,
        mapping: Mapping[bytes, float],
        *,
        nx: bool = False,
    ) -> int:
        raise ConnectionError("redis unavailable")


class _FakeSession:
    async def commit(self) -> None:
        return None


class _FailingEventRepository:
    async def write(self, record: object) -> None:
        raise RuntimeError("event store unavailable")


def _base_fingerprint() -> tuple[int, ...]:
    return tuple(range(NUM_HASH_FUNCTIONS))


def _similar_fingerprint(index: int) -> tuple[int, ...]:
    base = _base_fingerprint()
    return tuple(
        value + 10_000 + index if position < 8 else value
        for position, value in enumerate(base)
    )


def _different_fingerprint(index: int) -> tuple[int, ...]:
    offset = (index + 1) * 100_000
    return tuple(value + offset for value in range(NUM_HASH_FUNCTIONS))


@pytest.mark.asyncio
async def test_circuit_trips_at_cluster_threshold() -> None:
    breaker = SemanticCircuitBreaker(
        _FakeRedis(),
        cluster_threshold=3,
        similarity_threshold=0.7,
    )

    first = await breaker.evaluate(
        tenant_id="tenant-a",
        channel="whatsapp",
        ticket_id="ticket-1",
        fingerprint=_base_fingerprint(),
    )
    second = await breaker.evaluate(
        tenant_id="tenant-a",
        channel="whatsapp",
        ticket_id="ticket-2",
        fingerprint=_similar_fingerprint(2),
    )
    third = await breaker.evaluate(
        tenant_id="tenant-a",
        channel="whatsapp",
        ticket_id="ticket-3",
        fingerprint=_similar_fingerprint(3),
    )

    assert first == (SemanticCircuitState.CLOSED, 1)
    assert second == (SemanticCircuitState.CLOSED, 2)
    assert third == (SemanticCircuitState.TRIPPED, 3)


@pytest.mark.asyncio
async def test_circuit_stays_closed_for_dissimilar() -> None:
    breaker = SemanticCircuitBreaker(
        _FakeRedis(),
        cluster_threshold=3,
        similarity_threshold=0.7,
    )

    states = []
    for index in range(3):
        states.append(
            await breaker.evaluate(
                tenant_id="tenant-a",
                channel="email",
                ticket_id=f"ticket-{index}",
                fingerprint=_different_fingerprint(index),
            )
        )

    assert states == [
        (SemanticCircuitState.CLOSED, 1),
        (SemanticCircuitState.CLOSED, 1),
        (SemanticCircuitState.CLOSED, 1),
    ]


@pytest.mark.asyncio
async def test_circuit_window_expires_old_entries() -> None:
    now = 0.0

    def _now() -> float:
        return now

    breaker = SemanticCircuitBreaker(
        _FakeRedis(),
        window_seconds=300,
        cluster_threshold=2,
        similarity_threshold=0.7,
        time_provider=_now,
    )
    await breaker.evaluate(
        tenant_id="tenant-a",
        channel="whatsapp",
        ticket_id="ticket-old",
        fingerprint=_base_fingerprint(),
    )
    now = 301.0

    state = await breaker.evaluate(
        tenant_id="tenant-a",
        channel="whatsapp",
        ticket_id="ticket-new",
        fingerprint=_similar_fingerprint(1),
    )

    assert state == (SemanticCircuitState.CLOSED, 1)


@pytest.mark.asyncio
async def test_circuit_fail_open_on_redis_error() -> None:
    breaker = SemanticCircuitBreaker(_FailingRedis(), cluster_threshold=1)

    state = await breaker.evaluate(
        tenant_id="tenant-a",
        channel="whatsapp",
        ticket_id="ticket-1",
        fingerprint=_base_fingerprint(),
    )

    assert state == (SemanticCircuitState.CLOSED, 0)


@requires_postgres
@pytest.mark.asyncio
async def test_circuit_trip_persists_event(pg_session: AsyncSession) -> None:
    tenant_id = "test-pg-tenant"
    repository = SemanticCircuitEventRepository(pg_session)
    service = TicketIngressService(
        persistence=InMemoryBoundaryPersistence(),
        session=pg_session,
        circuit_breaker=SemanticCircuitBreaker(
            _FakeRedis(),
            cluster_threshold=1,
        ),
        circuit_event_repo=repository,
    )

    result = await service.process(
        external_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "scb2-trip-event")),
        channel="whatsapp",
        raw_content="the charger stopped working after one week of use",
        language_code="en",
        expected_tenant_id=tenant_id,
    )
    records = await repository.list_for_tenant(
        tenant_id=tenant_id,
        expected_tenant_id=tenant_id,
        channel="whatsapp",
    )

    assert len(records) == 1
    assert records[0].state == SemanticCircuitState.TRIPPED.value
    assert records[0].cluster_size is not None
    assert records[0].cluster_size >= 1
    assert records[0].trigger_ticket_id == result.ingress_id


@pytest.mark.asyncio
async def test_circuit_tenant_isolation() -> None:
    redis = _FakeRedis()
    breaker = SemanticCircuitBreaker(
        redis,
        cluster_threshold=2,
        similarity_threshold=0.7,
    )

    await breaker.evaluate(
        tenant_id="tenant-a",
        channel="whatsapp",
        ticket_id="a-1",
        fingerprint=_base_fingerprint(),
    )
    tenant_a = await breaker.evaluate(
        tenant_id="tenant-a",
        channel="whatsapp",
        ticket_id="a-2",
        fingerprint=_similar_fingerprint(2),
    )
    tenant_b = await breaker.evaluate(
        tenant_id="tenant-b",
        channel="whatsapp",
        ticket_id="b-1",
        fingerprint=_similar_fingerprint(3),
    )

    assert tenant_a == (SemanticCircuitState.TRIPPED, 2)
    assert tenant_b == (SemanticCircuitState.CLOSED, 1)


@pytest.mark.asyncio
async def test_ingress_continues_after_trip() -> None:
    service = TicketIngressService(
        persistence=InMemoryBoundaryPersistence(),
        session=cast(Any, _FakeSession()),
        circuit_breaker=SemanticCircuitBreaker(
            _FakeRedis(),
            cluster_threshold=1,
        ),
        circuit_event_repo=cast(Any, _FailingEventRepository()),
    )

    result = await service.process(
        external_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "scb2-ingress-trip")),
        channel="whatsapp",
        raw_content="the charger stopped working after one week of use",
        language_code="en",
        expected_tenant_id="tenant-a",
        semantic_quarantine_enabled=False,
    )

    assert result.ingress_id
    assert result.canonical_envelope_id


def test_serialization_roundtrip() -> None:
    breaker = SemanticCircuitBreaker(_FakeRedis())
    fingerprint = TextFingerprinter().fingerprint(
        "the charger stopped working after one week of use"
    )

    assert breaker._deserialize(breaker._serialize(fingerprint)) == fingerprint
