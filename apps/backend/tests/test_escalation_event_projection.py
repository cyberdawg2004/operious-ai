"""Phase 3-C escalation operational event projection tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app.escalation import (
    EscalationStatus,
    InMemoryEscalationPersistence,
    derive_escalation_event_id,
)
from app.escalation.persistence import EscalationRecord
from app.events import (
    InMemoryOperationalEventPersistence,
    OperationalEventRuntime,
    OperationalSubstrate,
)
from app.governance.capability.acts import OperationalAct
from app.governance.enums import Decision
from app.runtime.escalation_event_projection import (
    EscalationOperationalEventProjector,
    project_escalation_record,
)

_NOW = datetime(2026, 5, 22, 11, tzinfo=timezone.utc)
_ESCALATION_ID = "00000000-0000-0000-0000-000000003c11"
_SESSION_ID = "00000000-0000-0000-0000-000000003c12"
_DENY_ID = "00000000-0000-0000-0000-000000003c13"
_OVERRIDE_ID = "00000000-0000-0000-0000-000000003c14"


def _record(
    *,
    status: EscalationStatus = EscalationStatus.PENDING,
    tenant_id: str = "tenant-acme",
) -> EscalationRecord:
    return EscalationRecord(
        escalation_id=_ESCALATION_ID,
        session_id=_SESSION_ID,
        tenant_id=tenant_id,
        reason="deny",
        governance_decision_id=_DENY_ID,
        status=status.value,
        created_at=_NOW.isoformat(),
        resolved_at=(
            _NOW.replace(minute=30).isoformat()
            if status in {EscalationStatus.APPROVED, EscalationStatus.REJECTED}
            else None
        ),
        resolution="resolved" if status is not EscalationStatus.PENDING else None,
        resolved_by=(
            "principal-manager"
            if status in {EscalationStatus.APPROVED, EscalationStatus.REJECTED}
            else None
        ),
        metadata=(
            {"governance_override_decision_id": _OVERRIDE_ID}
            if status is EscalationStatus.APPROVED
            else {}
        ),
    )


def test_pending_escalation_projects_as_root_create_event() -> None:
    record = _record()

    event = project_escalation_record(record=record)

    assert event.event_id == str(
        derive_escalation_event_id(
            escalation_id=_ESCALATION_ID,
            status="pending",
        )
    )
    assert event.operational_act is OperationalAct.ESCALATION_CREATE
    assert event.substrate is OperationalSubstrate.ESCALATION
    assert event.causality.parent_event_id is None
    assert event.causality.depth == 0
    assert event.governance_decision is Decision.DENY
    assert event.governance_decision_id == _DENY_ID


def test_approved_escalation_projects_override_legality() -> None:
    record = _record(status=EscalationStatus.APPROVED)

    event = project_escalation_record(record=record)

    assert event.operational_act is OperationalAct.ESCALATION_APPROVE
    assert event.causality.parent_event_id == str(
        derive_escalation_event_id(
            escalation_id=_ESCALATION_ID,
            status="pending",
        )
    )
    assert event.causality.depth == 2
    assert event.governance_decision is Decision.ALLOW
    assert event.governance_decision_id == _OVERRIDE_ID


@pytest.mark.asyncio
async def test_escalation_projection_is_idempotent_and_tenant_scoped() -> None:
    records = InMemoryEscalationPersistence()
    await records.create_escalation(
        _record(),
        expected_tenant_id="tenant-acme",
    )
    event_store = InMemoryOperationalEventPersistence()
    projector = EscalationOperationalEventProjector(
        escalation_persistence=records,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    first = await projector.project_escalation(
        _ESCALATION_ID,
        expected_tenant_id="tenant-acme",
    )
    second = await projector.project_escalation(
        _ESCALATION_ID,
        expected_tenant_id="tenant-acme",
    )

    assert second.operational_event == first.operational_event
    assert await event_store.get_event(
        first.operational_event.event_id,
        expected_tenant_id="tenant-other",
    ) is None


@pytest.mark.asyncio
async def test_resolved_status_projects_new_deterministic_event() -> None:
    records = InMemoryEscalationPersistence()
    pending = _record()
    await records.create_escalation(pending, expected_tenant_id="tenant-acme")
    event_store = InMemoryOperationalEventPersistence()
    projector = EscalationOperationalEventProjector(
        escalation_persistence=records,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )
    pending_projection = await projector.project_escalation(
        _ESCALATION_ID,
        expected_tenant_id="tenant-acme",
    )
    approved = replace(
        pending,
        status=EscalationStatus.APPROVED.value,
        resolved_at=_NOW.replace(minute=30).isoformat(),
        resolution="approved",
        resolved_by="principal-manager",
        metadata={"governance_override_decision_id": _OVERRIDE_ID},
    )
    await records.update_escalation(
        approved,
        expected_tenant_id="tenant-acme",
    )

    approved_projection = await projector.project_escalation(
        _ESCALATION_ID,
        expected_tenant_id="tenant-acme",
    )

    assert approved_projection.operational_event.event_id == str(
        derive_escalation_event_id(
            escalation_id=_ESCALATION_ID,
            status="approved",
        )
    )
    assert (
        approved_projection.operational_event.event_id
        != pending_projection.operational_event.event_id
    )
