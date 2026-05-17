"""Persistence-invariant tests for the hardening substrate."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.hardening.enums import (
    ContainmentClassification,
    FailureClassification,
    HardeningSeverity,
    HardeningStatus,
    HardeningTraceKind,
    SubstrateName,
)
from app.hardening.exceptions import HardeningPersistenceError
from app.hardening.identity import (
    derive_audit_id,
    derive_failure_record_id,
)
from app.hardening.models.audit import HardeningAudit
from app.hardening.models.failure import (
    FailureContainmentRecord,
)
from app.hardening.persistence.memory import (
    InMemoryHardeningPersistence,
)


NOW = datetime.now(UTC)


@pytest.mark.asyncio
async def test_audit_is_write_once() -> None:
    p = InMemoryHardeningPersistence()
    audit = HardeningAudit(
        audit_id=derive_audit_id(seed="x"),
        seed="x",
        kind=HardeningTraceKind.AUDIT_RUN,
        status=HardeningStatus.COMPLETED,
        findings=(),
        started_at=NOW,
        ended_at=NOW,
    )
    await p.write_audit(audit)
    with pytest.raises(HardeningPersistenceError):
        await p.write_audit(audit)


@pytest.mark.asyncio
async def test_failure_record_is_write_once() -> None:
    p = InMemoryHardeningPersistence()
    record = FailureContainmentRecord(
        record_id=derive_failure_record_id(seed="r"),
        substrate=SubstrateName.AGENTS,
        classification=FailureClassification.SUBSTRATE_LOCAL,
        containment=ContainmentClassification.CONTAINED,
        severity=HardeningSeverity.LOW,
        summary="x",
        recorded_at=NOW,
        error_class_name="X",
    )
    await p.write_failure_record(record)
    with pytest.raises(HardeningPersistenceError):
        await p.write_failure_record(record)


@pytest.mark.asyncio
async def test_lists_are_sorted_by_timestamp() -> None:
    p = InMemoryHardeningPersistence()
    a = HardeningAudit(
        audit_id=derive_audit_id(seed="a"),
        seed="a",
        kind=HardeningTraceKind.AUDIT_RUN,
        status=HardeningStatus.COMPLETED,
        findings=(),
        started_at=datetime(2025, 1, 1, tzinfo=UTC),
        ended_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    b = HardeningAudit(
        audit_id=derive_audit_id(seed="b"),
        seed="b",
        kind=HardeningTraceKind.AUDIT_RUN,
        status=HardeningStatus.COMPLETED,
        findings=(),
        started_at=datetime(2024, 1, 1, tzinfo=UTC),
        ended_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    await p.write_audit(a)
    await p.write_audit(b)
    listed = await p.list_audits()
    assert listed[0].seed == "b"
    assert listed[1].seed == "a"
