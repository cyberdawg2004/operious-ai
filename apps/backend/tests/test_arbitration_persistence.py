"""`InMemoryArbitrationPersistence` discipline.

* Write-once.
* Deterministic ordering (runtime-instance, then sequence).
* Query filtering.
* Round-trip via `result_to_record`.
"""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

import pytest

from app.arbitration.enums import (
    ArbitrationAuthorityLevel,
    ArbitrationOutcome,
)
from app.arbitration.exceptions import (
    ArbitrationPersistenceError,
)
from app.arbitration.identity import (
    derive_case_id,
    derive_chain_id,
    derive_evaluation_id,
)
from app.arbitration.persistence.memory import (
    InMemoryArbitrationPersistence,
)
from app.arbitration.persistence.models import ArbitrationQuery
from app.arbitration.persistence.records import ArbitrationRecord


def _record(
    *,
    seed: str,
    sequence: int,
    outcome: ArbitrationOutcome = ArbitrationOutcome.ARBITRATION_RESOLVED,
    tenant_id: str | None = None,
    correlation_id: str | None = None,
    runtime_instance_id: uuid.UUID | None = None,
) -> ArbitrationRecord:
    now = datetime.now(tz=timezone.utc)
    return ArbitrationRecord(
        evaluation_id=derive_evaluation_id(seed=seed),
        chain_id=derive_chain_id(evaluator_names=("a",)),
        case_id=derive_case_id(seed=seed + ":case"),
        runtime_instance_id=runtime_instance_id or uuid.uuid4(),
        sequence=sequence,
        outcome=outcome,
        prevailing_authority_level=(
            ArbitrationAuthorityLevel.GOVERNANCE
            if outcome is ArbitrationOutcome.ARBITRATION_RESOLVED
            else None
        ),
        prevailing_authority_source_substrate=(
            "governance"
            if outcome is ArbitrationOutcome.ARBITRATION_RESOLVED
            else None
        ),
        prevailing_authority_source_id=(
            "g"
            if outcome is ArbitrationOutcome.ARBITRATION_RESOLVED
            else None
        ),
        prevailing_authority_verdict=(
            "deny"
            if outcome is ArbitrationOutcome.ARBITRATION_RESOLVED
            else None
        ),
        reason="",
        evaluator_names=("a",),
        findings=(),
        conflicts=(),
        deadlock_witnesses=(),
        signal_count=0,
        recommendation_count=0,
        iteration_count=1,
        max_iterations=3,
        correlation_id=correlation_id,
        request_id=None,
        tenant_id=tenant_id,
        started_at=now,
        ended_at=now,
        latency_ms=0.0,
        error=None,
        metadata={},
    )


@pytest.mark.asyncio
async def test_save_is_write_once() -> None:
    store = InMemoryArbitrationPersistence()
    record = _record(seed="r1", sequence=1)
    await store.save(record)
    with pytest.raises(ArbitrationPersistenceError):
        await store.save(record)


@pytest.mark.asyncio
async def test_get_returns_saved_record() -> None:
    store = InMemoryArbitrationPersistence()
    record = _record(seed="r1", sequence=1)
    await store.save(record)
    fetched = await store.get(record.evaluation_id)
    assert fetched is record


@pytest.mark.asyncio
async def test_list_orders_by_runtime_instance_then_sequence() -> None:
    store = InMemoryArbitrationPersistence()
    rt1 = uuid.UUID("00000000-0000-0000-0000-000000000001")
    rt2 = uuid.UUID("00000000-0000-0000-0000-000000000002")
    await store.save(
        _record(seed="r1", sequence=2, runtime_instance_id=rt1)
    )
    await store.save(
        _record(seed="r2", sequence=1, runtime_instance_id=rt1)
    )
    await store.save(
        _record(seed="r3", sequence=1, runtime_instance_id=rt2)
    )
    page = await store.list_records(ArbitrationQuery())
    assert [r.sequence for r in page.records] == [1, 2, 1]
    assert [r.runtime_instance_id for r in page.records] == [
        rt1,
        rt1,
        rt2,
    ]


@pytest.mark.asyncio
async def test_list_filters_combine_with_and() -> None:
    store = InMemoryArbitrationPersistence()
    await store.save(
        _record(
            seed="r1",
            sequence=1,
            tenant_id="t1",
            correlation_id="c1",
        )
    )
    await store.save(
        _record(
            seed="r2",
            sequence=2,
            tenant_id="t1",
            correlation_id="c2",
        )
    )
    await store.save(
        _record(
            seed="r3",
            sequence=3,
            tenant_id="t2",
            correlation_id="c1",
        )
    )

    page = await store.list_records(
        ArbitrationQuery(tenant_id="t1", correlation_id="c1")
    )
    assert page.total == 1


@pytest.mark.asyncio
async def test_list_supports_limit_and_offset() -> None:
    store = InMemoryArbitrationPersistence()
    rt = uuid.UUID("00000000-0000-0000-0000-000000000001")
    for i in range(5):
        await store.save(
            _record(
                seed=f"r{i}", sequence=i + 1, runtime_instance_id=rt
            )
        )
    page = await store.list_records(
        ArbitrationQuery(limit=2, offset=1)
    )
    assert page.total == 5
    assert [r.sequence for r in page.records] == [2, 3]
