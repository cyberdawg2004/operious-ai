"""Phase 6-F SOP ApprovalRecord operational event projection tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.events import (
    EventCausality,
    EventChronology,
    InMemoryOperationalEventPersistence,
    OperationalEvent,
    OperationalEventRuntime,
    OperationalLineageRelation,
    OperationalSubstrate,
    derive_event_id,
    normalize_operational_lineage,
)
from app.governance.capability.acts import OperationalAct
from app.runtime.sop_approval_event_projection import (
    SOPApprovalEventProjectionError,
    SOPApprovalOperationalEventProjector,
    project_sop_approval_record,
)
from app.sop_intelligence import (
    ApprovalRecord,
    ApprovalStatus,
    InMemorySOPApprovalPersistence,
    derive_approval_event_id,
)

_NOW = datetime(2026, 5, 24, 4, 30, tzinfo=timezone.utc)
_TENANT_ID = "tenant-anker"
_APPROVAL_ID = "00000000-0000-0000-0000-000000006f10"
_DOCUMENT_ID = "00000000-0000-0000-0000-000000006f11"
_SESSION_ID = "00000000-0000-0000-0000-000000006f12"
_PRINCIPAL_ID = "sop_intelligence_agent:v1"
_SESSION_RUNTIME_ID = uuid.UUID("00000000-0000-0000-0000-000000006f13")


def _record(
    *,
    status: ApprovalStatus = ApprovalStatus.PENDING_REVIEW,
    tenant_id: str = _TENANT_ID,
) -> ApprovalRecord:
    return ApprovalRecord(
        approval_id=_APPROVAL_ID,
        tenant_id=tenant_id,
        document_id=_DOCUMENT_ID,
        proposed_change=(
            "Add Anker PowerCore stopped-charging diagnostic checklist."
        ),
        evidence_sessions=(_SESSION_ID,),
        confidence=0.94,
        status=status.value,
        proposed_by=_PRINCIPAL_ID,
        reviewed_by=(
            "principal-manager"
            if status is not ApprovalStatus.PENDING_REVIEW
            else None
        ),
        created_at=_NOW.isoformat(),
        metadata={
            "anker_demo_scenario": True,
            "ticket_subject": "PowerCore does not charge",
            "proposal_only": True,
        },
    )


def test_pending_approval_projects_as_sop_proposal_event() -> None:
    record = _record()

    event = project_sop_approval_record(record=record)

    assert event.event_id == str(
        derive_approval_event_id(
            approval_id=_APPROVAL_ID,
            status=ApprovalStatus.PENDING_REVIEW.value,
        )
    )
    assert event.operational_act is OperationalAct.OI_SOP_APPROVAL_PROPOSE
    assert event.substrate is OperationalSubstrate.OI_SOP
    assert event.causality.parent_event_id is None
    assert event.causality.depth == 0
    assert event.tenant_id == _TENANT_ID
    assert event.principal_id == _PRINCIPAL_ID
    assert event.governance_decision is None
    assert event.governance_decision_id is None
    assert event.metadata["projection_source"] == "sop_approval_record"
    assert event.metadata["proposal_only"] is True
    assert event.metadata["evidence_sessions"] == [_SESSION_ID]


def test_approved_approval_projects_status_child_event() -> None:
    record = _record(status=ApprovalStatus.APPROVED)

    event = project_sop_approval_record(record=record)

    assert event.operational_act is OperationalAct.OI_SOP_APPROVAL_APPROVE
    assert event.event_id == str(
        derive_approval_event_id(
            approval_id=_APPROVAL_ID,
            status=ApprovalStatus.APPROVED.value,
        )
    )
    assert event.causality.parent_event_id == str(
        derive_approval_event_id(
            approval_id=_APPROVAL_ID,
            status=ApprovalStatus.PENDING_REVIEW.value,
        )
    )
    assert event.causality.depth == 1
    assert event.metadata["source_reviewed_by"] == "principal-manager"


@pytest.mark.asyncio
async def test_approval_projection_is_idempotent_and_tenant_scoped() -> None:
    records = InMemorySOPApprovalPersistence()
    await records.create_approval_record(
        _record(),
        expected_tenant_id=_TENANT_ID,
    )
    event_store = InMemoryOperationalEventPersistence()
    projector = SOPApprovalOperationalEventProjector(
        approval_persistence=records,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    first = await projector.project_approval(
        _APPROVAL_ID,
        expected_tenant_id=_TENANT_ID,
    )
    second = await projector.project_approval(
        _APPROVAL_ID,
        expected_tenant_id=_TENANT_ID,
    )

    assert second.operational_event == first.operational_event
    assert await event_store.get_event(
        first.operational_event.event_id,
        expected_tenant_id="tenant-other",
    ) is None


@pytest.mark.asyncio
async def test_approval_projection_requires_tenant_scope() -> None:
    projector = SOPApprovalOperationalEventProjector(
        approval_persistence=InMemorySOPApprovalPersistence(),
        event_runtime=OperationalEventRuntime(
            persistence=InMemoryOperationalEventPersistence()
        ),
    )

    with pytest.raises(SOPApprovalEventProjectionError):
        await projector.project_approval(_APPROVAL_ID)


def test_approval_projection_resolves_evidence_session_lineage() -> None:
    session_event_id = derive_event_id(
        operational_act=OperationalAct.SESSION_OPEN.value,
        substrate=OperationalSubstrate.SESSION.value,
        runtime_instance_id=_SESSION_RUNTIME_ID,
        sequence=0,
        tenant_id=_TENANT_ID,
        parent_event_id=None,
    )
    session_event = OperationalEvent(
        event_id=session_event_id,
        operational_act=OperationalAct.SESSION_OPEN,
        substrate=OperationalSubstrate.SESSION,
        causality=EventCausality(root_event_id=session_event_id),
        chronology=EventChronology(
            runtime_instance_id=_SESSION_RUNTIME_ID,
            sequence=0,
            occurred_at=_NOW,
        ),
        tenant_id=_TENANT_ID,
        metadata={"source_session_id": _SESSION_ID},
    )
    approval_event = project_sop_approval_record(record=_record())

    graph = normalize_operational_lineage((approval_event, session_event))

    assert graph.unresolved == ()
    assert (
        approval_event.event_id,
        OperationalLineageRelation.SOP_APPROVAL_EVIDENCES_SESSION,
        session_event.event_id,
    ) in {
        (edge.source_event_id, edge.relation, edge.target_event_id)
        for edge in graph.edges
    }
