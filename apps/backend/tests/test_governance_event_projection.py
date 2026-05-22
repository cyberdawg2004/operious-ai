"""Phase 2-D governance chronology projection tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.events import (
    InMemoryOperationalEventPersistence,
    OperationalEventQuery,
    OperationalEventRuntime,
    OperationalSubstrate,
)
from app.governance.capability.acts import (
    CAPABILITY_GOVERNED_ACTS,
    OperationalAct,
)
from app.governance.enums import Decision, EnforcementStage
from app.governance.persistence import (
    GovernanceDecisionRecord,
    GovernanceTraceRecord,
    InMemoryGovernanceRepository,
)
from app.runtime.governance_event_projection import (
    GovernanceEventProjectionError,
    GovernanceOperationalEventProjector,
    project_governance_decision_record,
)


def _decision(
    *,
    decision_id: str | None = None,
    decision: Decision = Decision.ALLOW,
    decided_at: datetime | None = None,
    correlation_id: str | None = None,
    tenant_id: str | None = "tenant-acme",
    request_id: str | None = "request-1",
    metadata: dict[str, object] | None = None,
) -> GovernanceDecisionRecord:
    return GovernanceDecisionRecord(
        decision_id=decision_id or str(uuid.uuid4()),
        decision=decision.value,
        stage=EnforcementStage.PRE_EXECUTION.value,
        policy_chain_id="governance-chain/phase-2d",
        reason="projection fixture",
        decided_at=(
            decided_at or datetime(2026, 5, 22, 1, tzinfo=timezone.utc)
        ).isoformat(),
        correlation_id=correlation_id,
        request_id=request_id,
        tenant_id=tenant_id,
        subject_kind="capability",
        governance_version="phase-2d/test",
        metadata=metadata or {},
    )


def _trace(
    decision: GovernanceDecisionRecord,
    *,
    metadata: dict[str, object] | None = None,
    final_decision: Decision | None = None,
) -> GovernanceTraceRecord:
    return GovernanceTraceRecord(
        decision_id=decision.decision_id,
        request_id=decision.request_id,
        correlation_id=decision.correlation_id,
        stage=decision.stage,
        action="execution.claim",
        resource="execution:intent",
        actor="principal-1",
        tenant_id=decision.tenant_id,
        subject_kind=decision.subject_kind,
        started_at=datetime(2026, 5, 22, 1, tzinfo=timezone.utc).isoformat(),
        ended_at=datetime(2026, 5, 22, 1, 0, 1, tzinfo=timezone.utc).isoformat(),
        latency_ms=5.0,
        status="ok",
        final_decision=(final_decision or Decision(decision.decision)).value,
        policy_chain_id=decision.policy_chain_id,
        rule_count=0,
        violation_count=0,
        restriction_count=0,
        enforcement_handler="allow",
        enforcement_status="ok",
        enforcement_latency_ms=1.0,
        metadata=metadata or {},
    )


def test_governance_decision_projects_to_canonical_event() -> None:
    decision_id = str(uuid.uuid4())
    decision = _decision(
        decision_id=decision_id,
        metadata={
            "principal_id": "principal-1",
            "organization_id": "org-1",
            "environment_id": "env-1",
        },
    )
    trace = _trace(
        decision,
        metadata={"tenant_authority_source": "header"},
    )

    projected = project_governance_decision_record(
        decision=decision,
        trace=trace,
    )

    assert projected.event_id == decision_id
    assert projected.operational_act is OperationalAct.GOVERNANCE_DECIDE
    assert projected.substrate is OperationalSubstrate.GOVERNANCE
    assert projected.causality.root_event_id == decision_id
    assert projected.causality.parent_event_id is None
    assert projected.causality.depth == 0
    assert projected.chronology.runtime_instance_id == uuid.UUID(decision_id)
    assert projected.chronology.sequence == 0
    assert projected.chronology.occurred_at == datetime.fromisoformat(
        decision.decided_at
    )
    assert projected.tenant_id == "tenant-acme"
    assert projected.principal_id == "principal-1"
    assert projected.organization_id == "org-1"
    assert projected.environment_id == "env-1"
    assert projected.tenant_authority_source == "header"
    assert projected.governance_decision is Decision.ALLOW
    assert projected.governance_decision_id == decision_id
    assert projected.metadata["projection_source"] == "governance_decision"
    assert projected.metadata["source_trace_present"] is True
    assert projected.metadata["source_decision_record"] == decision.to_dict()
    assert projected.metadata["source_trace_record"] == trace.to_dict()


@pytest.mark.asyncio
async def test_projector_projects_correlated_decisions_in_governance_order_idempotently() -> None:
    repo = InMemoryGovernanceRepository()
    event_store = InMemoryOperationalEventPersistence()
    projector = GovernanceOperationalEventProjector(
        governance_repository=repo,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )
    correlation_id = str(uuid.uuid4())
    second = _decision(
        decided_at=datetime(2026, 5, 22, 1, 0, 2, tzinfo=timezone.utc),
        correlation_id=correlation_id,
    )
    first = _decision(
        decided_at=datetime(2026, 5, 22, 1, 0, 1, tzinfo=timezone.utc),
        correlation_id=correlation_id,
    )
    third = _decision(
        decided_at=datetime(2026, 5, 22, 1, 0, 3, tzinfo=timezone.utc),
        correlation_id=correlation_id,
    )
    for decision in (second, first, third):
        await repo.record_decision(decision)

    projected = await projector.project_correlation_decisions(
        correlation_id,
        expected_tenant_id="tenant-acme",
    )
    repeated = await projector.project_correlation_decisions(
        correlation_id,
        expected_tenant_id="tenant-acme",
    )
    page = await event_store.list_events(
        OperationalEventQuery(
            substrate=OperationalSubstrate.GOVERNANCE,
            tenant_id="tenant-acme",
        )
    )

    assert [p.source_decision for p in projected] == [first, second, third]
    assert repeated == projected
    assert page.total == 3
    root_event_id = projected[0].operational_event.event_id
    for index, item in enumerate(projected):
        event = item.operational_event
        assert event.chronology.runtime_instance_id == uuid.UUID(correlation_id)
        assert event.chronology.sequence == index
        assert event.causality.root_event_id == root_event_id
        assert event.causality.depth == index
        if index == 0:
            assert event.causality.parent_event_id is None
        else:
            assert (
                event.causality.parent_event_id
                == projected[index - 1].operational_event.event_id
            )


@pytest.mark.asyncio
async def test_project_decision_uses_correlated_lineage() -> None:
    repo = InMemoryGovernanceRepository()
    event_store = InMemoryOperationalEventPersistence()
    projector = GovernanceOperationalEventProjector(
        governance_repository=repo,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )
    correlation_id = str(uuid.uuid4())
    first = _decision(
        decided_at=datetime(2026, 5, 22, 1, 0, 1, tzinfo=timezone.utc),
        correlation_id=correlation_id,
    )
    second = _decision(
        decided_at=datetime(2026, 5, 22, 1, 0, 2, tzinfo=timezone.utc),
        correlation_id=correlation_id,
    )
    await repo.record_decision(first)
    await repo.record_decision(second)

    projected = await projector.project_decision(
        second.decision_id,
        expected_tenant_id="tenant-acme",
    )

    assert projected.operational_event.chronology.runtime_instance_id == uuid.UUID(
        correlation_id
    )
    assert projected.operational_event.chronology.sequence == 1
    assert projected.operational_event.causality.root_event_id == first.decision_id
    assert (
        projected.operational_event.causality.parent_event_id
        == first.decision_id
    )


@pytest.mark.asyncio
async def test_projector_respects_tenant_scope() -> None:
    repo = InMemoryGovernanceRepository()
    event_store = InMemoryOperationalEventPersistence()
    projector = GovernanceOperationalEventProjector(
        governance_repository=repo,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )
    decision = _decision(tenant_id="tenant-acme")
    await repo.record_decision(decision)

    with pytest.raises(GovernanceEventProjectionError):
        await projector.project_decision(
            decision.decision_id,
            expected_tenant_id="tenant-other",
        )


@pytest.mark.asyncio
async def test_projector_rejects_cross_tenant_correlation_projection() -> None:
    repo = InMemoryGovernanceRepository()
    event_store = InMemoryOperationalEventPersistence()
    projector = GovernanceOperationalEventProjector(
        governance_repository=repo,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )
    correlation_id = str(uuid.uuid4())
    await repo.record_decision(
        _decision(correlation_id=correlation_id, tenant_id="tenant-acme")
    )
    await repo.record_decision(
        _decision(correlation_id=correlation_id, tenant_id="tenant-other")
    )

    with pytest.raises(GovernanceEventProjectionError):
        await projector.project_correlation_decisions(correlation_id)


def test_governance_trace_mismatch_is_rejected() -> None:
    decision = _decision(decision=Decision.ALLOW)
    trace = _trace(decision, final_decision=Decision.DENY)

    with pytest.raises(GovernanceEventProjectionError):
        project_governance_decision_record(decision=decision, trace=trace)


def test_governance_projection_act_does_not_inflate_capability_governance() -> None:
    assert OperationalAct.GOVERNANCE_DECIDE not in CAPABILITY_GOVERNED_ACTS


def test_governance_runtime_has_no_live_event_fabric_coupling() -> None:
    runtime_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "governance"
        / "enforcement"
        / "runtime.py"
    )
    source = runtime_path.read_text(encoding="utf-8")

    assert "OperationalEventRuntime" not in source
    assert "app.events" not in source
