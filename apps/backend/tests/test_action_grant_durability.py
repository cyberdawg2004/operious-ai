"""DB-backed durable action grant consumption tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import ClassVar

import pytest
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
from app.agents.results import ToolInvocationRequest, ToolInvocationResult
from app.agents.tools import BaseTool, ToolCapability, ToolInvoker, ToolRegistry
from app.agents.tools.action_governance import build_action_tool_governance_runtime
from app.agents.tools.actions import build_action_tool_registry
from app.agents.tools.approvals import (
    PostgresActionApprovalRepository,
    build_pending_action_approval,
)
from app.agents.tools.grants import (
    AGENT_ACTION_ACTOR_KEY,
    ActorMismatchError,
    AlreadyConsumedError,
    PostgresAgentActionGrantRepository,
    compute_agent_action_payload_hash,
    derive_agent_action_grant_id,
    derive_provider_idempotency_key,
)
from app.agents.tools.invoker import (
    AGENT_ACTION_BINDING_KEY,
    compute_agent_action_binding,
)
from app.agents.tools.orchestration import ActionOrchestrationRuntime
from app.agents.value_objects import CausalityMetadata
from app.governance.enums import Decision, EnforcementStage
from app.governance.persistence import (
    GovernanceDecisionRecord,
    PostgresGovernanceRepository,
)
from app.resolution.persistence import PostgresResolutionProposalPersistence
from app.runtime.timeline_runtime import TimelineRuntime
from app.services.action_approval_service import ActionApprovalService
from app.session.enums import SessionLifecyclePhase, SessionScope
from app.session.identity import SessionId, SessionLineageId
from app.session.persistence import PostgresSessionPersistence, SessionRecord
from tests.conftest import requires_postgres, set_pg_rls_tenant

pytestmark = [requires_postgres]

_TENANT_ID = "tenant-action-grants"
_OTHER_TENANT_ID = "tenant-action-grants-other"
_ACTOR = "agent:diagnostic-action-orchestrator"
_OTHER_ACTOR = "agent:other"
_TOOL_NAME = "refund.request"
_ACTION = "agent.tool_invocation"
_NOW = datetime(2026, 5, 31, 12, tzinfo=timezone.utc)
_PAYLOAD = {
    "order_id": "order-100",
    "product_sku": "A1771",
    "refund_amount_cents": 12500,
    "reason": "confirmed product defect",
}


@pytest.fixture
def pg_tenant_id() -> str:
    return _TENANT_ID


class _ActionTool(BaseTool):
    name: ClassVar[str] = _TOOL_NAME
    capability: ClassVar[ToolCapability] = ToolCapability.ACTION
    required_capabilities: ClassVar[frozenset[str]] = frozenset(
        {"tool.refund.request"}
    )

    def __init__(self, calls: list[dict[str, object]]) -> None:
        self._calls = calls

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
    ) -> ToolInvocationResult:
        self._calls.append(dict(request.payload))
        return ToolInvocationResult(output={"status": "success"})


async def test_grant_consumed_once_succeeds(pg_session: AsyncSession) -> None:
    decision_id = await _seed_grant(pg_session, seed="consume-once")
    repo = PostgresAgentActionGrantRepository(pg_session)

    consumed = await repo.consume_grant(
        decision_id=decision_id,
        tenant_id=_TENANT_ID,
        actor=_ACTOR,
    )

    assert consumed.consumed_at is not None
    assert consumed.consumed_by == _ACTOR


async def test_grant_second_consumption_raises_already_consumed(
    pg_session: AsyncSession,
) -> None:
    decision_id = await _seed_grant(pg_session, seed="consume-twice")
    repo = PostgresAgentActionGrantRepository(pg_session)
    await repo.consume_grant(
        decision_id=decision_id,
        tenant_id=_TENANT_ID,
        actor=_ACTOR,
    )

    with pytest.raises(AlreadyConsumedError):
        await repo.consume_grant(
            decision_id=decision_id,
            tenant_id=_TENANT_ID,
            actor=_ACTOR,
        )

    returned = (
        await pg_session.execute(
            text(
                """
                UPDATE public.agent_action_grants
                SET consumed_at = now(),
                    consumed_by = :actor
                WHERE decision_id = CAST(:decision_id AS uuid)
                  AND tenant_id = :tenant_id
                  AND consumed_at IS NULL
                RETURNING decision_id
                """
            ),
            {
                "decision_id": str(decision_id),
                "tenant_id": _TENANT_ID,
                "actor": _ACTOR,
            },
        )
    ).first()
    assert returned is None


async def test_consumption_survives_redis_unavailable(
    pg_session: AsyncSession,
) -> None:
    decision_id = await _seed_grant(pg_session, seed="redis-down")
    calls: list[dict[str, object]] = []
    invoker = ToolInvoker(
        tool_registry=_registry(_ActionTool(calls)),
        governance_runtime=build_action_tool_governance_runtime(
            persistence=PostgresGovernanceRepository(pg_session),
            redis_client=None,
        ),
        grant_repository=PostgresAgentActionGrantRepository(pg_session),
        redis_client=_RedisDown(),
    )

    envelope = await invoker.invoke(
        ToolInvocationRequest(tool_name=_TOOL_NAME, payload=dict(_PAYLOAD)),
        _context(actor=_ACTOR),
        invocation_ordinal=1,
        pre_approved_decision_id=str(decision_id),
    )

    assert envelope.is_ok
    assert envelope.provider_idempotency_key is not None
    assert calls == [dict(_PAYLOAD)]
    grant = await PostgresAgentActionGrantRepository(pg_session).get_grant(
        decision_id=decision_id,
        tenant_id=_TENANT_ID,
    )
    assert grant is not None
    assert grant.consumed_by == _ACTOR


async def test_actor_mismatch_rejected(pg_session: AsyncSession) -> None:
    decision_id = await _seed_grant(pg_session, seed="actor-mismatch")

    with pytest.raises(ActorMismatchError):
        await PostgresAgentActionGrantRepository(pg_session).consume_grant(
            decision_id=decision_id,
            tenant_id=_TENANT_ID,
            actor=_OTHER_ACTOR,
        )


async def test_manager_approval_reinvocation_still_works(
    pg_session: AsyncSession,
) -> None:
    await _seed_session(pg_session)
    source_decision_id = uuid.uuid5(
        uuid.NAMESPACE_URL, "manager-round-trip-source"
    )
    await PostgresGovernanceRepository(pg_session).record_decision(
        GovernanceDecisionRecord(
            decision_id=str(source_decision_id),
            decision=Decision.REQUIRE_APPROVAL.value,
            stage=EnforcementStage.PRE_EXECUTION.value,
            policy_chain_id="agent.action_tools.pre_execution",
            reason="refund exceeds auto-allow threshold",
            decided_at=_NOW.isoformat(),
            tenant_id=_TENANT_ID,
            subject_kind="agent_action",
            metadata={"_schema_version": "1"},
        )
    )
    approval = await PostgresActionApprovalRepository(pg_session).create_pending_approval(
        build_pending_action_approval(
            tenant_id=_TENANT_ID,
            session_id=_session_id(),
            execution_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "manager-execution")),
            tool_name="warranty.claim",
            idempotency_key=str(
                uuid.uuid5(uuid.NAMESPACE_URL, "manager-approval-idempotency")
            ),
            payload_json={
                "order_id": "order-100",
                "product_sku": "A1771",
                "issue_category": "product_defect",
                "customer_description": "Unit failed under warranty.",
            },
            governance_decision_id=str(source_decision_id),
            metadata={
                "action_type": "warranty_claim",
                "target_resource": "order:order-100:sku:A1771",
                AGENT_ACTION_ACTOR_KEY: _ACTOR,
            },
        ),
        expected_tenant_id=_TENANT_ID,
    )
    service = _approval_service(pg_session)

    resolved = await service.approve(
        approval_id=approval.approval_id,
        approved_by="principal-manager",
        note="approved",
        tenant_id=_TENANT_ID,
        expected_tenant_id=_TENANT_ID,
    )

    decision_id = resolved.metadata["manager_governance_decision_id"]
    manager_decision = await PostgresGovernanceRepository(pg_session).get_decision(
        str(decision_id),
        expected_tenant_id=_TENANT_ID,
    )
    assert manager_decision is not None
    assert manager_decision.metadata[AGENT_ACTION_ACTOR_KEY] == _ACTOR
    grant = await PostgresAgentActionGrantRepository(pg_session).get_grant(
        decision_id=uuid.UUID(str(decision_id)),
        tenant_id=_TENANT_ID,
    )
    assert grant is not None
    assert grant.actor == _ACTOR
    assert grant.consumed_by == _ACTOR


async def test_idempotency_key_deterministic() -> None:
    decision_id = uuid.uuid5(uuid.NAMESPACE_URL, "idempotency-decision")
    grant_id = derive_agent_action_grant_id(
        tenant_id=_TENANT_ID,
        decision_id=decision_id,
    )
    payload_hash = compute_agent_action_payload_hash(_PAYLOAD)

    first = derive_provider_idempotency_key(
        tenant_id=_TENANT_ID,
        grant_id=grant_id,
        payload_hash=payload_hash,
    )
    second = derive_provider_idempotency_key(
        tenant_id=_TENANT_ID,
        grant_id=grant_id,
        payload_hash=payload_hash,
    )

    assert first == second


async def test_grant_table_rls_isolation(pg_session: AsyncSession) -> None:
    tenant_a_decision = await _seed_grant(
        pg_session, seed="rls-a", tenant_id=_TENANT_ID
    )
    await _seed_grant(pg_session, seed="rls-b", tenant_id=_OTHER_TENANT_ID)

    try:
        await pg_session.execute(text("SET LOCAL ROLE operious_app_test"))
        await set_pg_rls_tenant(pg_session, _TENANT_ID)
        visible = (
            await pg_session.execute(
                text(
                    """
                    SELECT decision_id, tenant_id
                    FROM public.agent_action_grants
                    ORDER BY tenant_id
                    """
                )
            )
        ).mappings().all()
    finally:
        await pg_session.execute(text("RESET ROLE"))

    assert [(row["decision_id"], row["tenant_id"]) for row in visible] == [
        (tenant_a_decision, _TENANT_ID)
    ]


async def _seed_grant(
    session: AsyncSession,
    *,
    seed: str,
    tenant_id: str = _TENANT_ID,
    actor: str = _ACTOR,
    payload: dict[str, object] | None = None,
) -> uuid.UUID:
    await set_pg_rls_tenant(session, tenant_id)
    payload = dict(payload or _PAYLOAD)
    issued_at = datetime.now(timezone.utc)
    decision_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{seed}:decision")
    payload_hash = compute_agent_action_payload_hash(payload)
    binding_hash = compute_agent_action_binding(
        tenant_id=tenant_id,
        tool_name=_TOOL_NAME,
        actor=actor,
        payload=payload,
    )
    await PostgresGovernanceRepository(session).record_decision(
        GovernanceDecisionRecord(
            decision_id=str(decision_id),
            decision=Decision.ALLOW.value,
            stage=EnforcementStage.PRE_EXECUTION.value,
            policy_chain_id="manager.action_approval.v1",
            reason="manager_approved",
            decided_at=issued_at.isoformat(),
            tenant_id=tenant_id,
            subject_kind="manager_approval",
            metadata={
                AGENT_ACTION_BINDING_KEY: binding_hash,
                AGENT_ACTION_ACTOR_KEY: actor,
            },
        )
    )
    await PostgresAgentActionGrantRepository(session).issue_grant(
        tenant_id=tenant_id,
        decision_id=decision_id,
        tool_name=_TOOL_NAME,
        action=_ACTION,
        actor=actor,
        payload_hash=payload_hash,
        binding_hash=binding_hash,
        issued_at=issued_at,
        expires_at=None,
        metadata={"test_seed": seed},
    )
    return decision_id


def _registry(tool: BaseTool) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(tool)
    return registry


def _context(*, actor: str) -> AgentExecutionContext:
    agent_id = actor.removeprefix("agent:")
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id=agent_id,
            runtime_instance_id=derive_agent_runtime_instance_id(
                agent_ids=(agent_id,)
            ),
        ),
        execution=ExecutionIdentity(
            execution_id=uuid.uuid5(uuid.NAMESPACE_URL, "grant-runtime"),
            request_id="grant-runtime",
        ),
        capabilities=CapabilitySet(
            (
                AgentCapability(
                    name="tool.refund.request",
                    scope=CapabilityScope.INVOKE,
                ),
            )
        ),
        constraints=ExecutionConstraints(allowed_tools=(_TOOL_NAME,)),
        causality=CausalityMetadata(),
        tenant_id=_TENANT_ID,
        metadata={AGENT_ACTION_ACTOR_KEY: actor},
    )


async def _seed_session(session: AsyncSession) -> None:
    sid = SessionId(uuid.UUID(_session_id()))
    await PostgresSessionPersistence(session).save_session(
        SessionRecord(
            session_id=sid,
            scope=SessionScope.TENANT,
            external_handle="grant-manager-round-trip",
            tenant_id=_TENANT_ID,
            principal_id="principal-agent",
            opened_at=_NOW,
            lifecycle_phase=SessionLifecyclePhase.ACTIVE,
            lifecycle_recorded_at=_NOW,
            lifecycle_reason=None,
            lineage_id=SessionLineageId(uuid.UUID(_session_id())),
            root_session_id=sid,
            parent_session_id=None,
            ancestor_session_ids=(),
            lineage_depth=0,
            sequence_head=-1,
            revision=0,
        )
    )


def _approval_service(session: AsyncSession) -> ActionApprovalService:
    session_repository = PostgresSessionPersistence(session)
    governance_repository = PostgresGovernanceRepository(session)
    timeline = TimelineRuntime(persistence=session_repository)
    return ActionApprovalService(
        approval_repository=PostgresActionApprovalRepository(session),
        grant_repository=PostgresAgentActionGrantRepository(session),
        governance_repository=governance_repository,
        resolution_repository=PostgresResolutionProposalPersistence(session),
        session_repository=session_repository,
        orchestration_runtime=ActionOrchestrationRuntime(
            tool_invoker=ToolInvoker(
                tool_registry=build_action_tool_registry(),
                governance_runtime=build_action_tool_governance_runtime(
                    persistence=governance_repository,
                    redis_client=None,
                ),
                grant_repository=PostgresAgentActionGrantRepository(session),
                redis_client=None,
            ),
            approval_repository=PostgresActionApprovalRepository(session),
            timeline_runtime=timeline,
        ),
        timeline_runtime=timeline,
        session=session,
    )


def _session_id() -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "manager-session"))


class _RedisDown:
    async def set(self, *_args: object, **_kwargs: object) -> bool:
        raise RuntimeError("redis unavailable")
