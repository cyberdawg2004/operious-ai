"""Per-tenant fairness for the single-concurrency outbound send worker (#37).

The outbound worker runs --concurrency=1, so a tenant with a large backlog of
due replies could starve every other tenant head-of-line. The reconciler drains
due PENDING rows FAIRLY: at most ``per_tenant_limit`` per tenant per sweep, the
rest staying PENDING for the next sweep (never dropped — the row is durable).

These are hermetic (in-memory persistence, real selection logic — no mocks).
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.boundary.outbound.send_outbox import (
    InMemoryOutboundSendOutboxPersistence,
    OutboundSendOutboxId,
    OutboundSendOutboxRecord,
    OutboundSendOutboxRuntime,
    OutboundSendOutboxStatus,
)

_NOW = datetime(2026, 6, 9, tzinfo=timezone.utc)


def _record(*, tenant_id: str, ordinal: int) -> OutboundSendOutboxRecord:
    # Older `created_at` for lower ordinals so due-ordering is deterministic.
    created = _NOW - timedelta(minutes=10_000 - ordinal)
    return OutboundSendOutboxRecord(
        outbox_id=OutboundSendOutboxId(uuid.uuid4()),
        tenant_id=tenant_id,
        channel="email",
        action="customer_reply",
        draft_id=uuid.uuid4(),
        proposal_id=uuid.uuid4(),
        session_id=str(uuid.uuid4()),
        dispatch_id=str(uuid.uuid4()),
        governance_decision_id=uuid.uuid4(),
        recipient=f"{tenant_id}-{ordinal}@example.com",
        draft_body_sha256="a" * 64,
        status=OutboundSendOutboxStatus.PENDING,
        created_at=created,
        updated_at=created,
        next_attempt_at=None,
    )


async def _seed(
    persistence: InMemoryOutboundSendOutboxPersistence,
    counts: dict[str, int],
) -> None:
    for tenant_id, count in counts.items():
        for ordinal in range(count):
            await persistence.create_outbound_send_outbox(
                _record(tenant_id=tenant_id, ordinal=ordinal)
            )


@pytest.mark.asyncio
async def test_fair_drain_caps_each_tenant_per_sweep() -> None:
    persistence = InMemoryOutboundSendOutboxPersistence()
    runtime = OutboundSendOutboxRuntime(persistence=persistence)
    await _seed(persistence, {"tenant-a": 100, "tenant-b": 5, "tenant-c": 5})

    selected = await runtime.list_due_pending_fair(
        now=_NOW, per_tenant_limit=25, limit=1000
    )

    by_tenant = Counter(record.tenant_id for record in selected)
    # The noisy tenant is capped; the quiet tenants are fully drained.
    assert by_tenant["tenant-a"] == 25
    assert by_tenant["tenant-b"] == 5
    assert by_tenant["tenant-c"] == 5
    assert len(selected) == 35


@pytest.mark.asyncio
async def test_fair_drain_respects_total_limit() -> None:
    persistence = InMemoryOutboundSendOutboxPersistence()
    runtime = OutboundSendOutboxRuntime(persistence=persistence)
    await _seed(persistence, {"tenant-a": 50, "tenant-b": 50})

    selected = await runtime.list_due_pending_fair(
        now=_NOW, per_tenant_limit=40, limit=20
    )

    assert len(selected) == 20  # total cap honoured


@pytest.mark.asyncio
async def test_fair_drain_excludes_not_yet_due_rows() -> None:
    persistence = InMemoryOutboundSendOutboxPersistence()
    runtime = OutboundSendOutboxRuntime(persistence=persistence)
    future = replace(
        _record(tenant_id="tenant-a", ordinal=0),
        next_attempt_at=_NOW + timedelta(minutes=5),
    )
    await persistence.create_outbound_send_outbox(future)
    await persistence.create_outbound_send_outbox(
        _record(tenant_id="tenant-a", ordinal=1)
    )

    selected = await runtime.list_due_pending_fair(
        now=_NOW, per_tenant_limit=25, limit=1000
    )
    assert len(selected) == 1  # the future-dated row is not drained


@pytest.mark.asyncio
async def test_fair_drain_validates_arguments() -> None:
    runtime = OutboundSendOutboxRuntime(
        persistence=InMemoryOutboundSendOutboxPersistence()
    )
    with pytest.raises(ValueError):
        await runtime.list_due_pending_fair(now=_NOW, per_tenant_limit=0, limit=10)
    with pytest.raises(ValueError):
        await runtime.list_due_pending_fair(now=_NOW, per_tenant_limit=5, limit=0)
