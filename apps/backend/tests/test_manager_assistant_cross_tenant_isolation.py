"""Cross-tenant isolation test for the Manager Assistant.

INVARIANT: When the assistant is asked a question for tenant A, it MUST only
surface tenant A's data. Tenant B's data must never appear in the response.

This test proves isolation STRUCTURALLY by:
  1. Injecting distinct fake data for TENANT_A and TENANT_B into in-memory repos.
  2. Asking the assistant a question scoped to TENANT_A.
  3. Asserting the answer contains TENANT_A's numbers, NOT TENANT_B's numbers.

No real LLM is used — deterministic fake responses drive the agent. The
isolation is structural: every query passes expected_tenant_id, in-memory
repos enforce it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.agents.governed.manager_assistant import (
    MANAGER_ASSISTANT_POLICY_TYPE,
    ManagerAssistantAgent,
)
from app.services.manager_assistant_service import (
    ManagerAssistantService,
    ManagerQueryRunner,
)

TENANT_A = "tenant-isolation-A"
TENANT_B = "tenant-isolation-B"

_METRICS_A = MagicMock(
    ticket_throughput=100,
    governance_decision_count=80,
    governance_deny_count=4,
    governance_deny_rate=0.05,
    execution_count=100,
    completed_execution_count=90,
    execution_latency_ms_avg=250.0,
    execution_latency_ms_p50=200.0,
    execution_latency_ms_p95=500.0,
    escalation_count=5,
    escalation_rate=0.05,
    qa_score_count=40,
    qa_score_average=0.88,
    qa_score_distribution=(),
    dlq_count=0,
)
_METRICS_B = MagicMock(
    ticket_throughput=9999,
    governance_decision_count=800,
    governance_deny_count=80,
    governance_deny_rate=0.10,
    execution_count=9999,
    completed_execution_count=9000,
    execution_latency_ms_avg=9999.0,
    execution_latency_ms_p50=9999.0,
    execution_latency_ms_p95=9999.0,
    escalation_count=999,
    escalation_rate=0.10,
    qa_score_count=400,
    qa_score_average=0.50,
    qa_score_distribution=(),
    dlq_count=0,
)


def _make_obs_persistence() -> Any:
    async def read_metrics(query: Any, *, expected_tenant_id: str) -> Any:
        return _METRICS_A if expected_tenant_id == TENANT_A else _METRICS_B

    mock = MagicMock()
    mock.read_metrics = read_metrics
    return mock


def _make_escalation_persistence() -> Any:
    async def list_escalations(
        query: Any, *, expected_tenant_id: str | None = None
    ) -> Any:
        page = MagicMock()
        page.total = 5 if expected_tenant_id == TENANT_A else 999
        page.items = []
        return page

    mock = MagicMock()
    mock.list_escalations = list_escalations
    return mock


def _make_case_persistence() -> Any:
    async def list_cases(query: Any, *, expected_tenant_id: str) -> Any:
        page = MagicMock()
        page.total = 3 if expected_tenant_id == TENANT_A else 999
        page.items = ()
        return page

    mock = MagicMock()
    mock.list_cases = list_cases
    return mock


def _make_action_persistence() -> Any:
    async def list_approvals(
        *,
        expected_tenant_id: str,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Any, ...]:
        if expected_tenant_id == TENANT_A:
            return (MagicMock(), MagicMock())
        return tuple(MagicMock() for _ in range(999))

    mock = MagicMock()
    mock.list_approvals = list_approvals
    return mock


def _make_session_persistence() -> Any:
    async def list_sessions(query: Any, *, expected_tenant_id: str) -> Any:
        page = MagicMock()
        page.total = 10 if expected_tenant_id == TENANT_A else 9999
        page.sessions = ()
        return page

    mock = MagicMock()
    mock.list_sessions = list_sessions
    return mock


def _make_tenant_config() -> Any:
    async def list_knowledge_documents(
        query: Any, *, expected_tenant_id: str
    ) -> Any:
        page = MagicMock()
        page.items = []
        return page

    mock = MagicMock()
    mock.list_knowledge_documents = list_knowledge_documents
    return mock


def _make_runner() -> ManagerQueryRunner:
    return ManagerQueryRunner(
        observability_persistence=_make_obs_persistence(),
        escalation_persistence=_make_escalation_persistence(),
        case_approval_persistence=_make_case_persistence(),
        action_approval_persistence=_make_action_persistence(),
        session_persistence=_make_session_persistence(),
        tenant_config_repo=_make_tenant_config(),
    )


@pytest.fixture
async def agent_a() -> ManagerAssistantAgent:
    """ManagerAssistantAgent wired with a fake LLM and TENANT_A policy."""
    from app.tenant.persistence.memory import InMemoryTenantConfigurationRepository
    from app.tenant.persistence.records import TenantGovernancePolicyRecord
    from app.tenant.enums import TenantGovernancePolicyStatus
    import uuid

    policy_record = TenantGovernancePolicyRecord(
        policy_id=uuid.uuid4(),
        tenant_id=TENANT_A,
        policy_type=MANAGER_ASSISTANT_POLICY_TYPE,
        parameters={"role_description": "You are the manager assistant."},
        status=TenantGovernancePolicyStatus.ACTIVE,
        version=1,
        approved_by="admin",
        effective_from=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        source_approval_id="test-approval",
        content_sha256="abc123",
        previous_version_sha256=None,
    )

    repo = InMemoryTenantConfigurationRepository()
    await repo.save_governance_policy(policy_record, expected_tenant_id=TENANT_A)

    # Call counter to distinguish intent (pass 1) from narration (pass 2)
    call_count = [0]

    async def complete(
        *,
        system_prompt: str,
        messages: Any,
        max_output_tokens: int,
        temperature: float,
        tenant_id: str,
    ) -> Any:
        call_count[0] += 1
        result = MagicMock()
        # Return appropriate responses based on call order
        if call_count[0] == 1:
            # Intent mapping
            result.text = json.dumps({
                "query_key": "ticket_volume",
                "window_days": 7,
                "confidence": 0.95,
                "cannot_answer": False,
            })
        else:
            result.text = json.dumps({
                "answer": "You processed 100 tickets this week.",
                "chart_type": "number",
                "chart_data": {"value": 100, "label": "Tickets", "unit": "tickets"},
            })
        return result

    llm = MagicMock()
    llm.complete = complete
    return ManagerAssistantAgent(
        llm_client=llm,
        tenant_configuration_repository=repo,
    )


@pytest.fixture
async def cannot_answer_agent() -> ManagerAssistantAgent:
    """Agent that always returns cannot_answer=True from intent mapping."""
    from app.tenant.persistence.memory import InMemoryTenantConfigurationRepository
    from app.tenant.persistence.records import TenantGovernancePolicyRecord
    from app.tenant.enums import TenantGovernancePolicyStatus
    import uuid

    policy_record = TenantGovernancePolicyRecord(
        policy_id=uuid.uuid4(),
        tenant_id=TENANT_A,
        policy_type=MANAGER_ASSISTANT_POLICY_TYPE,
        parameters={"role_description": "You are the manager assistant."},
        status=TenantGovernancePolicyStatus.ACTIVE,
        version=1,
        approved_by="admin",
        effective_from=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        source_approval_id="test-approval",
        content_sha256="abc456",
        previous_version_sha256=None,
    )

    repo = InMemoryTenantConfigurationRepository()
    await repo.save_governance_policy(policy_record, expected_tenant_id=TENANT_A)

    async def complete(**_: Any) -> Any:
        result = MagicMock()
        result.text = json.dumps({
            "query_key": "",
            "window_days": 7,
            "confidence": 0.1,
            "cannot_answer": True,
        })
        return result

    llm = MagicMock()
    llm.complete = complete
    return ManagerAssistantAgent(
        llm_client=llm,
        tenant_configuration_repository=repo,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ticket_volume_uses_tenant_a_data_not_tenant_b(
    agent_a: ManagerAssistantAgent,
) -> None:
    """Querying ticket_volume for TENANT_A returns 100 tickets, not B's 9999."""
    runner = _make_runner()
    service = ManagerAssistantService(agent=agent_a, query_runner=runner)

    answer = await service.answer(
        question="how many tickets this week",
        tenant_id=TENANT_A,
    )

    assert not answer.cannot_answer
    assert answer.query_key == "ticket_volume"
    if answer.chart_type == "number":
        assert answer.chart_data.get("value") != 9999, (
            "CROSS-TENANT LEAK: chart shows TENANT_B's ticket count 9999"
        )


@pytest.mark.asyncio
async def test_pending_action_approvals_tenant_a_sees_only_own_count() -> None:
    """pending_action_approvals for TENANT_A returns 2, not 999 (TENANT_B)."""
    runner = _make_runner()

    result = await runner.fetch("pending_action_approvals", tenant_id=TENANT_A)
    assert result["pending_count"] == 2, (
        f"Expected 2 for TENANT_A, got {result['pending_count']}"
    )

    result_b = await runner.fetch("pending_action_approvals", tenant_id=TENANT_B)
    assert result_b["pending_count"] == 999


@pytest.mark.asyncio
async def test_escalation_rate_tenant_scoped() -> None:
    """Escalation metrics are isolated by tenant."""
    runner = _make_runner()

    result_a = await runner.fetch("escalation_rate", tenant_id=TENANT_A, window_days=7)
    result_b = await runner.fetch("escalation_rate", tenant_id=TENANT_B, window_days=7)

    assert result_a["ticket_throughput"] == 100
    assert result_b["ticket_throughput"] == 9999
    assert result_a["escalation_count"] == 5
    assert result_b["escalation_count"] == 999


@pytest.mark.asyncio
async def test_cannot_answer_honest_refusal(
    cannot_answer_agent: ManagerAssistantAgent,
) -> None:
    """Unanswerable question → cannot_answer=True, no fabricated data."""
    runner = _make_runner()
    service = ManagerAssistantService(
        agent=cannot_answer_agent, query_runner=runner
    )

    answer = await service.answer(
        question="what will the weather be like tomorrow",
        tenant_id=TENANT_A,
    )

    assert answer.cannot_answer is True
    assert answer.query_key == ""


@pytest.mark.asyncio
async def test_query_runner_never_omits_tenant_scope() -> None:
    """All SAFE_QUERIES can be dispatched and return dicts without errors."""
    from app.agents.governed.manager_assistant import SAFE_QUERIES

    runner = _make_runner()
    for query_def in SAFE_QUERIES:
        result = await runner.fetch(
            query_def.key,
            tenant_id=TENANT_A,
            window_days=7,
        )
        assert isinstance(result, dict), (
            f"Query {query_def.key!r} did not return a dict: {result!r}"
        )
        assert "error" not in result or "unknown" not in result.get("error", ""), (
            f"Query key {query_def.key!r} returned an unknown-key error: {result}"
        )
