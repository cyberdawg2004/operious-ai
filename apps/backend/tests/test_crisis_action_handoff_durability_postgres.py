"""Postgres-backed crisis action handoff durability coverage."""

from __future__ import annotations

import uuid
import inspect
import os
from datetime import datetime, timezone

import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import (
    AgentCapability,
    CapabilitySet,
    ExecutionConstraints,
)
from app.agents.context import AgentExecutionContext
from app.agents.enums import CapabilityScope
from app.agents.identity import (
    AgentIdentity,
    ExecutionIdentity,
    derive_agent_runtime_instance_id,
)
from app.agents.results import ToolInvocationRequest
from app.agents.tools import ToolInvoker
from app.agents.tools.action_governance import build_action_tool_governance_runtime
from app.agents.tools.actions import build_action_tool_registry
from app.agents.value_objects import CausalityMetadata
from app.dependencies.services import build_action_approval_service
from app.escalation import DeferredEscalationPublisher, EscalationAgentRuntime
from app.escalation.celery_publisher import CeleryEscalationPublisher
from app.escalation.persistence import PostgresEscalationPersistence
from app.governance.policies.crisis import _crisis_key
from app.governance.persistence import PostgresGovernanceRepository
from app.session.enums import SessionLifecyclePhase, SessionScope
from app.session.identity import SessionId, SessionLineageId
from app.session.persistence import PostgresSessionPersistence, SessionRecord
from app.workers import agent_tasks
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]

_TENANT_ID = "tenant-crisis-action-handoff"
_SESSION_ID = "00000000-0000-0000-0000-00000000ca01"
_EXECUTION_ID = "00000000-0000-0000-0000-00000000ca02"
_NOW = datetime(2026, 6, 11, tzinfo=timezone.utc)


@pytest.fixture
def pg_tenant_id() -> str:
    return _TENANT_ID


async def test_action_invoker_crisis_handoff_is_durable_before_flush(
    pg_session: AsyncSession,
) -> None:
    await _ensure_tenant(pg_session)
    await _seed_session(pg_session)
    crisis_activation = await _real_redis()
    crisis_key = _crisis_key(_TENANT_ID, "escalate_all")
    governance_repository = PostgresGovernanceRepository(pg_session)
    session_repository = PostgresSessionPersistence(pg_session)
    deferred_publisher = DeferredEscalationPublisher(
        delegate=CeleryEscalationPublisher(),
        escalation_runtime=EscalationAgentRuntime(
            escalation_persistence=PostgresEscalationPersistence(pg_session),
            governance_repository=governance_repository,
            session_persistence=session_repository,
        ),
        session=pg_session,
        publisher_id="test:action-orchestration",
    )
    try:
        await crisis_activation.delete(crisis_key)
        await crisis_activation.set(crisis_key, "{}")
        invoker = ToolInvoker(
            tool_registry=build_action_tool_registry(),
            governance_runtime=build_action_tool_governance_runtime(
                persistence=governance_repository,
                redis_client=crisis_activation,
                tenant_configuration_repository=None,
            ),
            escalation_publisher=deferred_publisher,
        )

        envelope = await invoker.invoke(
            ToolInvocationRequest(
                tool_name="refund.request",
                payload={
                    "order_id": "order-crisis-1",
                    "product_sku": "A1771",
                    "refund_amount_cents": 1299,
                    "refund_reason": "crisis durability regression",
                },
                metadata={
                    "session_id": _SESSION_ID,
                    "issue_category": "refund",
                    "target_resource": "order:order-crisis-1:sku:A1771",
                },
            ),
            _context(),
            invocation_ordinal=1,
        )
    finally:
        await crisis_activation.delete(crisis_key)
        await crisis_activation.aclose()

    assert envelope.is_denied
    assert envelope.trace.governance_decision_id is not None
    assert envelope.trace.metadata.get("crisis_policy") == "crisis.escalate_all"
    decision_id = str(envelope.trace.governance_decision_id)
    outbox = (
        await pg_session.execute(
            text(
                """
                SELECT eo.status, eo.publisher_id, eo.claim_id, eo.metadata
                FROM public.escalation_outbox eo
                JOIN public.escalation_records er
                  ON er.escalation_id = eo.escalation_id
                WHERE er.governance_decision_id = CAST(:decision_id AS uuid)
                  AND er.tenant_id = :tenant_id
                """
            ),
            {
                "decision_id": decision_id,
                "tenant_id": _TENANT_ID,
            },
        )
    ).mappings().one()
    assert outbox["status"] == "pending"
    assert outbox["publisher_id"] is None
    assert outbox["claim_id"] is None
    assert outbox["metadata"]["source_decision"] == "deny"
    assert outbox["metadata"]["source_governance_decision_id"] == decision_id
    pending = await EscalationAgentRuntime(
        escalation_persistence=PostgresEscalationPersistence(pg_session),
        governance_repository=governance_repository,
        session_persistence=session_repository,
    ).list_pending_outbox_records(expected_tenant_id=_TENANT_ID)
    assert len(pending) == 1
    assert pending[0].metadata["source_governance_decision_id"] == decision_id


def test_action_orchestration_and_worker_invokers_receive_durable_publisher() -> None:
    service_source = inspect.getsource(build_action_approval_service)
    worker_source = inspect.getsource(agent_tasks._action_orchestration_runtime)

    assert "DeferredEscalationPublisher(" in service_source
    assert "escalation_publisher=deferred_escalation_publisher" in service_source
    assert "post_commit_flush=deferred_escalation_publisher.flush" in service_source
    assert "DeferredEscalationPublisher(" in worker_source
    assert "escalation_publisher=deferred_escalation_publisher" in worker_source
    assert "post_commit_flushes.append(deferred_escalation_publisher.flush)" in worker_source


async def _real_redis() -> Redis:
    url = os.environ.get("CRISIS_ACTION_TEST_REDIS_URL", "redis://localhost:6379/0")
    client = Redis.from_url(url, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:
        await client.aclose()
        pytest.skip(f"real Redis unavailable for crisis activation: {exc}")
    return client


async def _seed_session(session: AsyncSession) -> None:
    sid = SessionId(uuid.UUID(_SESSION_ID))
    await PostgresSessionPersistence(session).save_session(
        SessionRecord(
            session_id=sid,
            scope=SessionScope.TENANT,
            external_handle="crisis-action-handoff",
            tenant_id=_TENANT_ID,
            principal_id="principal-crisis-action",
            opened_at=_NOW,
            lifecycle_phase=SessionLifecyclePhase.ACTIVE,
            lifecycle_recorded_at=_NOW,
            lifecycle_reason=None,
            lineage_id=SessionLineageId(uuid.UUID(_SESSION_ID)),
            root_session_id=sid,
            parent_session_id=None,
            ancestor_session_ids=(),
            lineage_depth=0,
            sequence_head=-1,
            revision=0,
        )
    )


async def _ensure_tenant(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            INSERT INTO public.tenants (tenant_id)
            VALUES (:tenant_id)
            ON CONFLICT (tenant_id) DO NOTHING
            """
        ),
        {"tenant_id": _TENANT_ID},
    )


def _context() -> AgentExecutionContext:
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="diagnostic-action-orchestrator",
            runtime_instance_id=derive_agent_runtime_instance_id(
                agent_ids=("diagnostic-action-orchestrator",)
            ),
        ),
        execution=ExecutionIdentity(
            execution_id=uuid.UUID(_EXECUTION_ID),
            request_id="req-crisis-action-handoff",
            correlation_id="corr-crisis-action-handoff",
        ),
        capabilities=CapabilitySet(
            (
                AgentCapability(
                    name="tool.refund.request",
                    scope=CapabilityScope.INVOKE,
                ),
            )
        ),
        constraints=ExecutionConstraints(allowed_tools=("refund.request",)),
        causality=CausalityMetadata(),
        tenant_id=_TENANT_ID,
        metadata={},
    )
