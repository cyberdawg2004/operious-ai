"""Coordination-policy persistence — records, serializers, repository."""

from __future__ import annotations

import pytest

from app.coordination.policy.exceptions import (
    CoordinationPolicyPersistenceError,
)
from app.coordination.policy.persistence import (
    CoordinationPolicyEscalationRecord,
    CoordinationPolicyFindingRecord,
    CoordinationPolicyQuery,
    CoordinationPolicyRecord,
    CoordinationPolicyRestrictionRecord,
    InMemoryCoordinationPolicyPersistence,
)


def _restriction_record() -> CoordinationPolicyRestrictionRecord:
    return CoordinationPolicyRestrictionRecord(
        kind="priority_cap",
        target="agent:planner",
        reason="cap",
        policy_id="p1",
        rule_id="r1",
        value={"cap": 20},
    )


def _escalation_record() -> CoordinationPolicyEscalationRecord:
    return CoordinationPolicyEscalationRecord(
        kind="human_review",
        target="approver:platform",
        reason="sensitive",
        policy_id="p1",
        rule_id="r1",
    )


def _finding_record() -> CoordinationPolicyFindingRecord:
    return CoordinationPolicyFindingRecord(
        finding_id="f1",
        evaluator_name="topology",
        scope="topology",
        decision="restrict",
        code="topology.restricted",
        message="cap",
        policy_id="p1",
        rule_id="r1",
        detected_at="2024-01-01T00:00:00+00:00",
        restrictions=(_restriction_record(),),
        escalations=(),
    )


def _record() -> CoordinationPolicyRecord:
    return CoordinationPolicyRecord(
        evaluation_id="e1",
        chain_id="c1",
        runtime_instance_id="i1",
        sequence=1,
        coordination_id="co1",
        coordination_message_id="cm1",
        sender_id="agent:retriever",
        recipient_id="agent:planner",
        recipient_kind="agent",
        direction="agent_to_agent",
        message_type="handoff",
        priority=20,
        aggregate_decision="restrict",
        evaluator_names=("topology",),
        finding_count=1,
        restriction_count=1,
        escalation_count=0,
        correlation_id="corr1",
        parent_coordination_id=None,
        parent_message_id=None,
        request_id="req1",
        tenant_id="tenant:t1",
        started_at="2024-01-01T00:00:00+00:00",
        ended_at="2024-01-01T00:00:00+00:00",
        latency_ms=1.0,
        reason="restrict",
        error=None,
        findings=(_finding_record(),),
        restrictions=(_restriction_record(),),
        escalations=(_escalation_record(),),
        metadata={"k": "v"},
    )


# ─── Record round-trips ──────────────────────────────────────────────


def test_restriction_record_round_trip() -> None:
    rec = _restriction_record()
    assert CoordinationPolicyRestrictionRecord.from_dict(rec.to_dict()) == rec


def test_escalation_record_round_trip() -> None:
    rec = _escalation_record()
    assert CoordinationPolicyEscalationRecord.from_dict(rec.to_dict()) == rec


def test_finding_record_round_trip() -> None:
    rec = _finding_record()
    assert CoordinationPolicyFindingRecord.from_dict(rec.to_dict()) == rec


def test_apex_record_round_trip() -> None:
    rec = _record()
    assert CoordinationPolicyRecord.from_dict(rec.to_dict()) == rec


# ─── In-memory repository ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_evaluation_is_write_once() -> None:
    repo = InMemoryCoordinationPolicyPersistence()
    await repo.record_evaluation(_record())
    with pytest.raises(CoordinationPolicyPersistenceError):
        await repo.record_evaluation(_record())


@pytest.mark.asyncio
async def test_get_evaluation_returns_persisted_record() -> None:
    repo = InMemoryCoordinationPolicyPersistence()
    await repo.record_evaluation(_record())
    fetched = await repo.get_evaluation("e1")
    assert fetched is not None
    assert fetched.evaluation_id == "e1"


@pytest.mark.asyncio
async def test_query_filters_by_aggregate_decision() -> None:
    repo = InMemoryCoordinationPolicyPersistence()
    await repo.record_evaluation(_record())
    page = await repo.query_evaluations(
        CoordinationPolicyQuery(aggregate_decision="restrict")
    )
    assert len(page.items) == 1
    page = await repo.query_evaluations(
        CoordinationPolicyQuery(aggregate_decision="deny")
    )
    assert len(page.items) == 0


@pytest.mark.asyncio
async def test_query_returns_items_in_sequence_order() -> None:
    repo = InMemoryCoordinationPolicyPersistence()
    # Three records with different sequence numbers.
    for i in (3, 1, 2):
        await repo.record_evaluation(
            CoordinationPolicyRecord(
                evaluation_id=f"e{i}",
                chain_id="c1",
                runtime_instance_id="i1",
                sequence=i,
                coordination_id=f"co{i}",
                coordination_message_id=f"cm{i}",
                sender_id="s",
                recipient_id="r",
                recipient_kind="agent",
                direction="agent_to_agent",
                message_type="handoff",
                priority=20,
                aggregate_decision="allow",
                evaluator_names=("topology",),
                finding_count=0,
                restriction_count=0,
                escalation_count=0,
                correlation_id=None,
                parent_coordination_id=None,
                parent_message_id=None,
                request_id=None,
                tenant_id=None,
                started_at="t",
                ended_at="t",
                latency_ms=0.0,
                reason="allow",
            )
        )
    page = await repo.query_evaluations(CoordinationPolicyQuery(limit=10))
    sequences = [r.sequence for r in page.items]
    assert sequences == [1, 2, 3]
