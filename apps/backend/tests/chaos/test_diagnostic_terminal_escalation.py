from __future__ import annotations

import inspect
import json
from typing import Any

import pytest
from sqlalchemy import text

from app.cognition.models import DiagnosticLLMCompletion, DiagnosticLLMUsage
from app.db.session import get_owner_session_factory
from app.db.tenant_context import set_current_tenant
from app.escalation.celery_publisher import CeleryEscalationPublisher
from app.queues import QUEUE_ESCALATION
from app.workers import agent_tasks
from app.workers.agent_tasks import execute_diagnostic_agent_runtime
from tests.conftest import requires_postgres


@requires_postgres
@pytest.mark.asyncio
@pytest.mark.chaos
async def test_terminal_semantic_block_escalates_with_grounding_handoff(
    committed_burst_seed,
    suppress_supervisor_enqueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del suppress_supervisor_enqueue

    tenant_id = "chaos-semantic-escalation-tenant"
    await committed_burst_seed["seed_tenant"](tenant_id)
    execution_id = await committed_burst_seed["seed_execution"](tenant_id)

    async def rejected_completion(*args: object, **kwargs: object) -> object:
        del args, kwargs
        text_body = {
            "summary": (
                "Charging issue needs legal review before replacement "
                "discussion."
            ),
            "category": "charging_issue",
            "confidence": 0.92,
            "reasoning": (
                "The ticket is charging-related, but the draft introduces "
                "legal review without grounding."
            ),
        }
        return DiagnosticLLMCompletion(
            provider="operious-deterministic-llm",
            model="operious-diagnostic-local-v1",
            text=json.dumps(text_body, sort_keys=True),
            usage=DiagnosticLLMUsage(
                prompt_tokens=100,
                completion_tokens=25,
                total_tokens=125,
            ),
            raw_metadata={"scripted": "semantic-terminal-escalation"},
        )

    monkeypatch.setattr(
        agent_tasks,
        "get_initialized_quota_runtime",
        lambda: None,
    )
    monkeypatch.setattr(
        "app.cognition.llm.DeterministicDiagnosticLLMClient.complete",
        rejected_completion,
    )

    set_current_tenant(tenant_id)
    result = await execute_diagnostic_agent_runtime(
        execution_id=execution_id,
        tenant_id=tenant_id,
        worker_id="pytest:semantic-terminal-escalation",
    )

    assert result["status"] == "escalated"
    assert result["error_class"] == "SEMANTIC_REJECTION"
    assert result["retry_queue"] == QUEUE_ESCALATION
    assert result["dead_letter_task_recorded"] is False
    assert result["execution_failed"] is True
    decision_id = str(result["governance_decision_id"])
    escalation_id = str(result["escalation_id"])
    outbox_id = str(result["escalation_outbox_id"])
    session_id = str(result["session_id"])
    await CeleryEscalationPublisher().publish_governance_denial(
        governance_decision_id=decision_id,
        tenant_id=tenant_id,
        session_id=session_id,
    )

    async with get_owner_session_factory()() as session:
        decision = (
            await session.execute(
                text(
                    """
                    SELECT decision, policy_chain_id, evaluated_rules
                    FROM governance_decisions
                    WHERE decision_id = CAST(:decision_id AS uuid)
                      AND tenant_id = :tenant_id
                    """
                ),
                {"decision_id": decision_id, "tenant_id": tenant_id},
            )
        ).one()
        escalation = (
            await session.execute(
                text(
                    """
                    SELECT escalation_id::text, metadata
                    FROM escalation_records
                    WHERE governance_decision_id = CAST(:decision_id AS uuid)
                      AND tenant_id = :tenant_id
                    """
                ),
                {"decision_id": decision_id, "tenant_id": tenant_id},
            )
        ).one()
        outbox = (
            await session.execute(
                text(
                    """
                    SELECT outbox_id::text, metadata
                    FROM escalation_outbox
                    WHERE escalation_id = CAST(:escalation_id AS uuid)
                      AND tenant_id = :tenant_id
                    """
                ),
                {"escalation_id": escalation_id, "tenant_id": tenant_id},
            )
        ).one()
        counts = (
            await session.execute(
                text(
                    """
                    SELECT
                        (SELECT COUNT(*)
                         FROM escalation_records
                         WHERE tenant_id = :tenant_id
                           AND governance_decision_id =
                               CAST(:decision_id AS uuid)) AS escalations,
                        (SELECT COUNT(*)
                         FROM escalation_outbox
                         WHERE tenant_id = :tenant_id
                           AND escalation_id =
                               CAST(:escalation_id AS uuid)) AS outboxes,
                        (SELECT COUNT(*)
                         FROM dead_letter_tasks
                         WHERE tenant_id = :tenant_id) AS dead_letters
                    """
                ),
                {
                    "decision_id": decision_id,
                    "escalation_id": escalation_id,
                    "tenant_id": tenant_id,
                },
            )
        ).one()
        execution_state = (
            await session.execute(
                text(
                    """
                    SELECT state
                    FROM execution_records
                    WHERE execution_id = CAST(:execution_id AS uuid)
                      AND tenant_id = :tenant_id
                    """
                ),
                {"execution_id": execution_id, "tenant_id": tenant_id},
            )
        ).scalar_one()
        handoff_event = (
            await session.execute(
                text(
                    """
                    SELECT payload
                    FROM session_events
                    WHERE session_id = CAST(:session_id AS uuid)
                      AND annotation =
                          'grounding_escalation_handoff_created'
                    ORDER BY sequence DESC
                    LIMIT 1
                    """
                ),
                {"session_id": session_id},
            )
        ).scalar_one()

    assert decision.decision == "deny"
    assert decision.policy_chain_id == "cognition.diagnostic.terminal_block"
    assert escalation.escalation_id == escalation_id
    assert outbox.outbox_id == outbox_id
    assert counts.escalations == 1
    assert counts.outboxes == 1
    assert counts.dead_letters == 0
    assert execution_state == "failed"

    evaluated_rules = _json_value(decision.evaluated_rules)
    rule_metadata = evaluated_rules[0]["metadata"]
    escalation_metadata = _json_value(escalation.metadata)
    outbox_metadata = _json_value(outbox.metadata)
    event_payload = _json_value(handoff_event)

    assert outbox_metadata["source"] == "diagnostic_terminal_block"
    assert escalation_metadata["structured_handoff"] == rule_metadata[
        "structured_handoff"
    ]
    handoff = escalation_metadata["structured_handoff"]
    assert handoff["execution_id"] == execution_id
    assert handoff["error_class"] == "SEMANTIC_REJECTION"
    assert "legal review" in handoff["blocked_completion_excerpt"]
    assert "retrieved_citations" in handoff
    grounding = escalation_metadata["grounding_trace"]
    correction = grounding["semantic_self_correction"]
    assert correction["semantic_self_correction_attempted"] is True
    assert correction["semantic_self_correction_outcome"] == "rejected"
    assert correction[
        "semantic_self_correction_corrected_introduced_terms"
    ] == ["legal"]
    assert event_payload["structured_handoff"] == handoff
    assert event_payload["grounding_trace"] == grounding


def test_terminal_diagnostic_escalation_uses_existing_pipeline() -> None:
    source = inspect.getsource(agent_tasks._escalate_terminal_diagnostic_block)

    assert "EscalationAgentRuntime(" in source
    assert ".prepare_governance_denial_outbox(" in source
    assert "CeleryEscalationPublisher().publish_governance_denial(" in source
    assert "_record_dead_letter_task" not in source
    assert "_dead_letter_execution_record" not in source


def test_terminal_block_decision_id_is_stable_for_replay() -> None:
    work_item = agent_tasks._DiagnosticExecutionWorkItem(
        execution_id="11111111-1111-1111-1111-111111111111",
        attempt_id="22222222-2222-2222-2222-222222222222",
        attempt_number=1,
        dispatch_id="33333333-3333-3333-3333-333333333333",
        session_id="44444444-4444-4444-4444-444444444444",
        tenant_id="tenant-terminal-block-stability",
        content="Device stopped charging.",
    )
    failure = {"error_class": "SEMANTIC_REJECTION"}

    first = agent_tasks._diagnostic_terminal_block_decision_id(
        work_item=work_item,
        failure=failure,
    )
    second = agent_tasks._diagnostic_terminal_block_decision_id(
        work_item=work_item,
        failure=failure,
    )

    assert first == second


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value
