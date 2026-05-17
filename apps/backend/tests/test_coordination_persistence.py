"""Coordination persistence — record serialisation + repository semantics.

Properties pinned:

* `CoordinationRecord.to_dict() / from_dict()` round-trips losslessly,
* `envelope_to_record(env)` then `record_to_envelope(rec)` returns
  an observable-equal envelope,
* write-once: re-recording the same `coordination_id` raises,
* `query_envelopes` filters honour every supported field,
* query results are ordered by `(runtime_instance_id, sequence)`
  ascending — the substrate's canonical replay order.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.coordination.contracts.messages import CoordinationMessage
from app.coordination.envelopes import CoordinationEnvelope
from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
    CoordinationPriority,
    CoordinationStatus,
)
from app.coordination.exceptions import CoordinationPersistenceError
from app.coordination.identity import (
    as_coordination_id,
    as_correlation_id,
    as_message_id,
    derive_coordination_id,
    derive_correlation_id,
    derive_message_id,
)
from app.coordination.models.payload import CoordinationPayload
from app.coordination.models.recipients import CoordinationRecipient
from app.coordination.persistence.memory import (
    InMemoryCoordinationPersistence,
)
from app.coordination.persistence.models import CoordinationQuery
from app.coordination.persistence.records import CoordinationRecord
from app.coordination.persistence.serializers import (
    envelope_to_record,
    record_to_envelope,
)


# ─── Helpers ─────────────────────────────────────────────────────────


_NOW = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _envelope(
    *,
    coord_id: str = "coord:1",
    msg_id: str = "msg:1",
    sender: str = "agent:retriever",
    recipient: str = "agent:planner",
    runtime_instance_id: uuid.UUID | None = None,
    sequence: int = 1,
    status: CoordinationStatus = CoordinationStatus.DISPATCHED,
    direction: CoordinationDirection = CoordinationDirection.AGENT_TO_AGENT,
    message_type: CoordinationMessageType = CoordinationMessageType.HANDOFF,
    correlation_seed: str | None = None,
    tenant: str | None = "tenant:acme",
) -> CoordinationEnvelope:
    runtime_instance_id = runtime_instance_id or uuid.UUID(
        "00000000-0000-0000-0000-000000000aaa"
    )
    correlation_id = (
        derive_correlation_id(seed=correlation_seed)
        if correlation_seed
        else None
    )
    payload = CoordinationPayload(
        content_type="operious/agent-handoff",
        body={"context_token": "tok-123", "next_action": "plan"},
        schema_version="1",
        metadata={"replay_hint": "deterministic"},
    )
    return CoordinationEnvelope(
        coordination_id=derive_coordination_id(seed=coord_id),
        message=CoordinationMessage(
            message_id=derive_message_id(seed=msg_id),
            message_type=message_type,
            sender_id=sender,
            recipient=CoordinationRecipient(
                recipient_id=recipient,
                kind="agent",
                tenant_id=tenant,
                metadata={"role": "planner"},
            ),
            payload=payload,
            priority=CoordinationPriority.NORMAL,
            in_reply_to=None,
            created_at=_NOW,
            metadata={"caller_tag": "test"},
        ),
        direction=direction,
        status=status,
        sequence=sequence,
        runtime_instance_id=runtime_instance_id,
        correlation_id=correlation_id,
        parent_coordination_id=None,
        parent_message_id=None,
        request_id="req-1",
        tenant_id=tenant,
        governance_decision_id=uuid.UUID(
            "00000000-0000-0000-0000-000000000bbb"
        ),
        governance_chain_id="coord.default",
        created_at=_NOW,
        dispatched_at=_NOW,
        metadata={"envelope_tag": "x"},
    )


# ─── Serialisation round-trip ────────────────────────────────────────


def test_record_to_dict_round_trip() -> None:
    env = _envelope()
    record = envelope_to_record(env)
    again = CoordinationRecord.from_dict(record.to_dict())
    assert again == record


def test_envelope_to_record_round_trip() -> None:
    env = _envelope()
    rec = envelope_to_record(env)
    reconstructed = record_to_envelope(rec)
    assert reconstructed.coordination_id == env.coordination_id
    assert reconstructed.message == env.message
    assert reconstructed.direction == env.direction
    assert reconstructed.status == env.status
    assert reconstructed.sequence == env.sequence
    assert reconstructed.runtime_instance_id == env.runtime_instance_id
    assert reconstructed.correlation_id == env.correlation_id
    assert reconstructed.parent_coordination_id == env.parent_coordination_id
    assert reconstructed.parent_message_id == env.parent_message_id
    assert reconstructed.request_id == env.request_id
    assert reconstructed.tenant_id == env.tenant_id
    assert reconstructed.governance_decision_id == env.governance_decision_id
    assert reconstructed.governance_chain_id == env.governance_chain_id
    assert reconstructed.created_at == env.created_at
    assert reconstructed.dispatched_at == env.dispatched_at
    assert dict(reconstructed.metadata) == dict(env.metadata)


def test_record_serialisation_is_byte_stable() -> None:
    """Same envelope → byte-identical dict (replay-grade)."""
    env = _envelope()
    a = envelope_to_record(env).to_dict()
    b = envelope_to_record(env).to_dict()
    assert a == b


# ─── In-memory repository semantics ─────────────────────────────────


@pytest.mark.asyncio
async def test_record_envelope_persists_and_reads_back() -> None:
    repo = InMemoryCoordinationPersistence()
    env = _envelope()
    rec = envelope_to_record(env)
    await repo.record_envelope(rec)
    fetched = await repo.get_envelope(rec.coordination_id)
    assert fetched == rec


@pytest.mark.asyncio
async def test_record_envelope_is_write_once() -> None:
    repo = InMemoryCoordinationPersistence()
    rec = envelope_to_record(_envelope())
    await repo.record_envelope(rec)
    with pytest.raises(CoordinationPersistenceError):
        await repo.record_envelope(rec)


@pytest.mark.asyncio
async def test_query_orders_by_runtime_instance_then_sequence() -> None:
    repo = InMemoryCoordinationPersistence()
    rt_a = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
    rt_b = uuid.UUID("00000000-0000-0000-0000-0000000000b2")

    # Mixed insertion order across two runtime instances + sequences.
    for rt, seq, coord in [
        (rt_b, 2, "b:2"),
        (rt_a, 1, "a:1"),
        (rt_b, 1, "b:1"),
        (rt_a, 2, "a:2"),
    ]:
        env = _envelope(
            coord_id=coord,
            msg_id=coord + ":msg",
            runtime_instance_id=rt,
            sequence=seq,
        )
        await repo.record_envelope(envelope_to_record(env))

    page = await repo.query_envelopes(CoordinationQuery())
    order = [(r.runtime_instance_id, r.sequence) for r in page.items]
    assert order == sorted(order)


@pytest.mark.asyncio
async def test_query_filters_by_correlation_id() -> None:
    repo = InMemoryCoordinationPersistence()
    a = _envelope(coord_id="a", msg_id="a:m", correlation_seed="op:1")
    b = _envelope(coord_id="b", msg_id="b:m", correlation_seed="op:2")
    c = _envelope(coord_id="c", msg_id="c:m", correlation_seed="op:1")
    for env in (a, b, c):
        await repo.record_envelope(envelope_to_record(env))

    corr_1 = str(derive_correlation_id(seed="op:1"))
    page = await repo.query_envelopes(
        CoordinationQuery(correlation_id=corr_1)
    )
    coord_ids = [r.coordination_id for r in page.items]
    assert sorted(coord_ids) == sorted(
        [
            str(derive_coordination_id(seed="a")),
            str(derive_coordination_id(seed="c")),
        ]
    )


@pytest.mark.asyncio
async def test_query_pagination_respects_offset_and_limit() -> None:
    repo = InMemoryCoordinationPersistence()
    rt = uuid.UUID("00000000-0000-0000-0000-0000000000cc")
    for i in range(5):
        env = _envelope(
            coord_id=f"p:{i}",
            msg_id=f"p:{i}:m",
            runtime_instance_id=rt,
            sequence=i + 1,
        )
        await repo.record_envelope(envelope_to_record(env))

    page = await repo.query_envelopes(CoordinationQuery(limit=2, offset=1))
    assert len(page.items) == 2
    assert page.total == 5
    assert page.offset == 1


# ─── Tracing handle: as_* coercers used at boundaries ───────────────


def test_boundary_coercion_round_trips() -> None:
    raw = uuid.uuid4()
    assert as_coordination_id(str(raw)) == raw
    assert as_message_id(str(raw)) == raw
    assert as_correlation_id(str(raw)) == raw
