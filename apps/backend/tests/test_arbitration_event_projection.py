"""Phase 2-I arbitration chronology projection tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid

import pytest

from app.arbitration.enums import (
    ArbitrationAuthorityLevel,
    ArbitrationOutcome,
)
from app.arbitration.identity import (
    derive_case_id,
    derive_chain_id,
    derive_evaluation_id,
)
from app.arbitration.persistence import (
    ArbitrationRecord,
    InMemoryArbitrationPersistence,
)
from app.events import (
    EventCausality,
    EventChronology,
    EventId,
    InMemoryOperationalEventPersistence,
    OperationalEvent,
    OperationalEventQuery,
    OperationalEventRuntime,
    OperationalLineageRelation,
    OperationalSubstrate,
    derive_event_id,
    normalize_operational_lineage,
)
from app.governance.capability.acts import OperationalAct
from app.governance.enums import Decision
from app.runtime.arbitration_event_projection import (
    ArbitrationEventProjectionError,
    ArbitrationOperationalEventProjector,
    project_arbitration_record,
)


_NOW = datetime(2026, 5, 22, 9, tzinfo=timezone.utc)


def _record(
    *,
    seed: str = "arbitration-projection",
    case_seed: str = "case-projection",
    sequence: int = 0,
    tenant_id: str | None = "tenant-acme",
    started_at: datetime | None = None,
    runtime_instance_id: uuid.UUID | None = None,
    source_substrate: str | None = "governance",
    source_id: str | None = None,
    governance_decision_id: uuid.UUID | None = None,
) -> ArbitrationRecord:
    start = started_at or _NOW
    source_identifier = source_id or str(uuid.uuid4())
    return ArbitrationRecord(
        evaluation_id=derive_evaluation_id(seed=seed),
        chain_id=derive_chain_id(evaluator_names=("authority_precedence",)),
        case_id=derive_case_id(seed=case_seed),
        runtime_instance_id=runtime_instance_id or uuid.uuid4(),
        sequence=sequence,
        outcome=ArbitrationOutcome.ARBITRATION_RESOLVED,
        prevailing_authority_level=ArbitrationAuthorityLevel.GOVERNANCE,
        prevailing_authority_source_substrate=source_substrate,
        prevailing_authority_source_id=source_identifier,
        prevailing_authority_verdict="deny",
        reason="projection fixture",
        evaluator_names=("authority_precedence",),
        findings=(),
        conflicts=(),
        deadlock_witnesses=(),
        signal_count=1,
        recommendation_count=0,
        iteration_count=1,
        max_iterations=3,
        correlation_id="correlation-arbitration-projection",
        request_id="request-arbitration-projection",
        tenant_id=tenant_id,
        started_at=start,
        ended_at=start + timedelta(milliseconds=15),
        latency_ms=15.0,
        error=None,
        governance_decision_id=governance_decision_id,
        governance_chain_id="governance-chain-1",
        metadata={
            "tenant_authority_source": "header",
            "principal_id": "principal-1",
            "organization_id": "org-1",
            "environment_id": "env-1",
            "fixture_uuid": uuid.uuid4(),
            "fixture_time": start,
        },
    )


def _governance_event(
    *,
    decision_id: str,
    tenant_id: str = "tenant-acme",
) -> OperationalEvent:
    event_id = EventId(decision_id)
    return OperationalEvent(
        event_id=event_id,
        operational_act=OperationalAct.GOVERNANCE_DECIDE,
        substrate=OperationalSubstrate.GOVERNANCE,
        causality=EventCausality(root_event_id=event_id),
        chronology=EventChronology(
            runtime_instance_id=uuid.UUID(decision_id),
            sequence=0,
            occurred_at=_NOW,
        ),
        tenant_id=tenant_id,
        governance_decision=Decision.ALLOW,
        governance_decision_id=decision_id,
        metadata={"source_decision_id": decision_id},
    )


def _execution_event(
    *,
    execution_id: str,
    tenant_id: str = "tenant-acme",
) -> OperationalEvent:
    event_id = derive_event_id(
        operational_act=OperationalAct.EXECUTION_REQUEST.value,
        substrate=OperationalSubstrate.EXECUTION.value,
        runtime_instance_id=uuid.UUID(execution_id),
        sequence=0,
        tenant_id=tenant_id,
        parent_event_id=None,
    )
    return OperationalEvent(
        event_id=event_id,
        operational_act=OperationalAct.EXECUTION_REQUEST,
        substrate=OperationalSubstrate.EXECUTION,
        causality=EventCausality(root_event_id=event_id),
        chronology=EventChronology(
            runtime_instance_id=uuid.UUID(execution_id),
            sequence=0,
            occurred_at=_NOW,
        ),
        tenant_id=tenant_id,
        metadata={"execution_id": execution_id},
    )


def test_arbitration_record_projects_to_canonical_event() -> None:
    decision_id = uuid.uuid4()
    record = _record(
        source_id=str(decision_id),
        governance_decision_id=decision_id,
    )

    projected = project_arbitration_record(record=record)

    assert projected.event_id == str(record.evaluation_id)
    assert projected.operational_act is OperationalAct.ARBITRATION_EVALUATE
    assert projected.substrate is OperationalSubstrate.ARBITRATION
    assert projected.causality.root_event_id == projected.event_id
    assert projected.causality.parent_event_id is None
    assert projected.causality.depth == 0
    assert projected.chronology.runtime_instance_id == record.runtime_instance_id
    assert projected.chronology.sequence == record.sequence
    assert projected.chronology.occurred_at == record.started_at
    assert projected.tenant_id == "tenant-acme"
    assert projected.principal_id == "principal-1"
    assert projected.organization_id == "org-1"
    assert projected.environment_id == "env-1"
    assert projected.tenant_authority_source == "header"
    assert projected.governance_decision is Decision.ALLOW
    assert projected.governance_decision_id == str(decision_id)
    assert projected.metadata["projection_source"] == (
        "arbitration_evaluation"
    )
    assert projected.metadata["source_outcome"] == "arbitration_resolved"
    assert projected.metadata["source_record"]["evaluation_id"] == (
        str(record.evaluation_id)
    )
    json.dumps(projected.metadata)


@pytest.mark.asyncio
async def test_projector_projects_evaluation_idempotently() -> None:
    repo = InMemoryArbitrationPersistence()
    event_store = InMemoryOperationalEventPersistence()
    record = _record()
    await repo.save(record)
    projector = ArbitrationOperationalEventProjector(
        arbitration_persistence=repo,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    first = await projector.project_evaluation(
        record.evaluation_id,
        expected_tenant_id="tenant-acme",
    )
    second = await projector.project_evaluation(
        str(record.evaluation_id),
        expected_tenant_id="tenant-acme",
    )
    page = await event_store.list_events(
        OperationalEventQuery(
            substrate=OperationalSubstrate.ARBITRATION,
            tenant_id="tenant-acme",
        )
    )

    assert second == first
    assert page.total == 1
    assert first.source_record == record


@pytest.mark.asyncio
async def test_projector_projects_case_evaluations_in_source_order() -> None:
    repo = InMemoryArbitrationPersistence()
    event_store = InMemoryOperationalEventPersistence()
    runtime_id = uuid.uuid4()
    later = _record(
        seed="case-later",
        sequence=2,
        started_at=_NOW + timedelta(seconds=2),
        runtime_instance_id=runtime_id,
    )
    earlier = _record(
        seed="case-earlier",
        sequence=1,
        started_at=_NOW + timedelta(seconds=1),
        runtime_instance_id=runtime_id,
    )
    await repo.save(later)
    await repo.save(earlier)
    projector = ArbitrationOperationalEventProjector(
        arbitration_persistence=repo,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    projected = await projector.project_case_evaluations(
        earlier.case_id,
        expected_tenant_id="tenant-acme",
    )

    assert [p.source_record for p in projected] == [earlier, later]
    first = projected[0].operational_event
    second = projected[1].operational_event
    assert first.causality.root_event_id == first.event_id
    assert first.causality.parent_event_id is None
    assert first.causality.depth == 0
    assert second.causality.root_event_id == first.event_id
    assert second.causality.parent_event_id == first.event_id
    assert second.causality.depth == 1
    assert [p.operational_event.chronology.sequence for p in projected] == [
        1,
        2,
    ]


@pytest.mark.asyncio
async def test_projector_resolves_single_evaluation_case_lineage() -> None:
    repo = InMemoryArbitrationPersistence()
    event_store = InMemoryOperationalEventPersistence()
    earlier = _record(
        seed="single-earlier",
        sequence=1,
        started_at=_NOW + timedelta(seconds=1),
    )
    later = _record(
        seed="single-later",
        sequence=2,
        started_at=_NOW + timedelta(seconds=2),
    )
    await repo.save(earlier)
    await repo.save(later)
    projector = ArbitrationOperationalEventProjector(
        arbitration_persistence=repo,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    projected = await projector.project_evaluation(
        later.evaluation_id,
        expected_tenant_id="tenant-acme",
    )

    event = projected.operational_event
    assert event.causality.root_event_id == str(earlier.evaluation_id)
    assert event.causality.parent_event_id == str(earlier.evaluation_id)
    assert event.causality.depth == 1


@pytest.mark.asyncio
async def test_projector_respects_tenant_scope() -> None:
    repo = InMemoryArbitrationPersistence()
    event_store = InMemoryOperationalEventPersistence()
    record = _record(tenant_id="tenant-acme")
    await repo.save(record)
    projector = ArbitrationOperationalEventProjector(
        arbitration_persistence=repo,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    with pytest.raises(ArbitrationEventProjectionError):
        await projector.project_evaluation(
            record.evaluation_id,
            expected_tenant_id="tenant-other",
        )


@pytest.mark.asyncio
async def test_projector_rejects_cross_tenant_case_projection() -> None:
    repo = InMemoryArbitrationPersistence()
    event_store = InMemoryOperationalEventPersistence()
    tenant_a = _record(seed="tenant-a", sequence=1, tenant_id="tenant-a")
    tenant_b = _record(seed="tenant-b", sequence=2, tenant_id="tenant-b")
    await repo.save(tenant_a)
    await repo.save(tenant_b)
    projector = ArbitrationOperationalEventProjector(
        arbitration_persistence=repo,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    with pytest.raises(ArbitrationEventProjectionError):
        await projector.project_case_evaluations(tenant_a.case_id)


def test_arbitration_projection_normalizes_governance_authority_lineage() -> None:
    decision_id = str(uuid.uuid4())
    governance_event = _governance_event(decision_id=decision_id)
    arbitration_event = project_arbitration_record(
        record=_record(source_substrate="governance", source_id=decision_id)
    )

    graph = normalize_operational_lineage(
        (governance_event, arbitration_event)
    )

    assert (
        arbitration_event.event_id,
        OperationalLineageRelation.ARBITRATES_AUTHORITY,
        governance_event.event_id,
    ) in {
        (edge.source_event_id, edge.relation, edge.target_event_id)
        for edge in graph.edges
    }


def test_arbitration_projection_normalizes_execution_authority_lineage() -> None:
    execution_id = str(uuid.uuid4())
    execution_event = _execution_event(execution_id=execution_id)
    arbitration_event = project_arbitration_record(
        record=_record(source_substrate="execution", source_id=execution_id)
    )

    graph = normalize_operational_lineage((execution_event, arbitration_event))

    assert (
        arbitration_event.event_id,
        OperationalLineageRelation.ARBITRATES_AUTHORITY,
        execution_event.event_id,
    ) in {
        (edge.source_event_id, edge.relation, edge.target_event_id)
        for edge in graph.edges
    }


def test_arbitration_runtime_has_no_live_event_fabric_coupling() -> None:
    runtime_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "arbitration"
        / "runtime"
        / "runtime.py"
    )
    source = runtime_path.read_text(encoding="utf-8")

    assert "OperationalEventRuntime" not in source
    assert "app.events" not in source
