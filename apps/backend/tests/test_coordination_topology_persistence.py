"""`InMemoryCoordinationTopologyPersistence` + record round-trip.

* records serialise / deserialise byte-stably,
* write-once per ``evaluation_id`` raises,
* query returns deterministic
  `(runtime_instance_id, sequence)`-ascending pages,
* query filters narrow correctly.
"""

from __future__ import annotations

import pytest

from app.coordination.topology.exceptions import (
    CoordinationTopologyPersistenceError,
)
from app.coordination.topology.persistence.memory import (
    InMemoryCoordinationTopologyPersistence,
)
from app.coordination.topology.persistence.models import (
    CoordinationTopologyQuery,
)
from app.coordination.topology.persistence.records import (
    CoordinationTopologyFindingRecord,
    CoordinationTopologyRecord,
)


def _finding_record(seed: str = "f") -> CoordinationTopologyFindingRecord:
    return CoordinationTopologyFindingRecord(
        finding_id=f"00000000-0000-0000-0000-00000000000{seed[-1]}",
        evaluator_name="allowed_path",
        decision="allowed",
        code="path.allowed",
        message="ok",
        edge_id=None,
        path_id=None,
        boundary_id=None,
        source_node_id=None,
        target_node_id=None,
        detected_at="2026-05-15T12:00:00+00:00",
    )


def _record(
    evaluation_id: str,
    *,
    sequence: int = 1,
    runtime_instance_id: str = "11111111-1111-1111-1111-111111111111",
    aggregate_decision: str = "allowed",
    tenant_id: str | None = None,
) -> CoordinationTopologyRecord:
    return CoordinationTopologyRecord(
        evaluation_id=evaluation_id,
        chain_id="chain-id",
        topology_id="topology-id",
        topology_name="rt",
        topology_version="v1",
        runtime_instance_id=runtime_instance_id,
        sequence=sequence,
        coordination_id="c",
        coordination_message_id="m",
        sender_id="a",
        recipient_id="b",
        recipient_kind="agent",
        direction="agent_to_agent",
        message_type="request",
        priority=20,
        aggregate_decision=aggregate_decision,
        evaluator_names=("allowed_path",),
        finding_count=1,
        chain_depth=0,
        max_chain_depth=4,
        matched_edge_id=None,
        matched_path_id=None,
        correlation_id=None,
        parent_coordination_id=None,
        parent_message_id=None,
        request_id=None,
        tenant_id=tenant_id,
        started_at="2026-05-15T12:00:00+00:00",
        ended_at="2026-05-15T12:00:00.001+00:00",
        latency_ms=1.0,
        reason="ok",
        error=None,
        findings=(_finding_record(),),
    )


def test_record_round_trip() -> None:
    record = _record("11111111-1111-1111-1111-111111111111")
    blob = record.to_dict()
    restored = CoordinationTopologyRecord.from_dict(blob)
    assert restored == record


@pytest.mark.asyncio
async def test_write_once_per_evaluation_id() -> None:
    store = InMemoryCoordinationTopologyPersistence()
    record = _record("11111111-1111-1111-1111-111111111111")
    await store.record_evaluation(record)
    with pytest.raises(CoordinationTopologyPersistenceError):
        await store.record_evaluation(record)


@pytest.mark.asyncio
async def test_query_returns_sorted_pages() -> None:
    store = InMemoryCoordinationTopologyPersistence()
    for i in (3, 1, 2):
        await store.record_evaluation(
            _record(f"22222222-0000-0000-0000-00000000000{i}", sequence=i)
        )
    page = await store.query_evaluations(CoordinationTopologyQuery())
    assert tuple(r.sequence for r in page.items) == (1, 2, 3)


@pytest.mark.asyncio
async def test_query_filters_by_decision() -> None:
    store = InMemoryCoordinationTopologyPersistence()
    await store.record_evaluation(
        _record(
            "33333333-0000-0000-0000-000000000001",
            sequence=1,
            aggregate_decision="allowed",
        )
    )
    await store.record_evaluation(
        _record(
            "33333333-0000-0000-0000-000000000002",
            sequence=2,
            aggregate_decision="denied",
        )
    )
    page = await store.query_evaluations(
        CoordinationTopologyQuery(aggregate_decision="denied")
    )
    assert tuple(r.evaluation_id for r in page.items) == (
        "33333333-0000-0000-0000-000000000002",
    )


@pytest.mark.asyncio
async def test_query_filters_by_tenant() -> None:
    store = InMemoryCoordinationTopologyPersistence()
    await store.record_evaluation(
        _record(
            "44444444-0000-0000-0000-000000000001",
            sequence=1,
            tenant_id="t1",
        )
    )
    await store.record_evaluation(
        _record(
            "44444444-0000-0000-0000-000000000002",
            sequence=2,
            tenant_id="t2",
        )
    )
    page = await store.query_evaluations(
        CoordinationTopologyQuery(tenant_id="t1")
    )
    assert len(page.items) == 1
    assert page.items[0].tenant_id == "t1"
