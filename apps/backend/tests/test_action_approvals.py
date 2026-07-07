"""PR_RT7 manager action approval endpoint tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.redis as redis_module
import app.dependencies.services as service_dependencies
import app.main as main_module
from app.agents.tools.approvals import (
    ActionApprovalRecord,
    PostgresActionApprovalRepository,
    build_pending_action_approval,
)
from app.agents.tools.grants import (
    AGENT_ACTION_ACTOR_KEY,
    PostgresAgentActionGrantRepository,
)
from app.agents.tools.invoker import (
    AGENT_ACTION_BINDING_KEY,
    compute_agent_action_binding,
)
from app.agents.tools.orchestration import ActionOrchestrationRuntime, ActionOutcome
from app.dependencies.authority import (
    require_tenant_actions_approve,
    require_tenant_operations_read,
)
from app.dependencies.database import get_db_session
from app.governance.enums import Decision, EnforcementStage
from app.governance.persistence import (
    DecisionQuery,
    GovernanceDecisionRecord,
    PostgresGovernanceRepository,
)
from app.identity import AuthorityContext
from app.main import create_app
from app.resolution.enums import (
    ResolutionAutonomyDecision,
    ResolutionGovernanceVerdict,
    ResolutionProposalStatus,
    ResolutionSupervisorVerdict,
)
from app.resolution.identity import ResolutionProposalId
from app.resolution.persistence import (
    PostgresResolutionProposalPersistence,
    ResolutionProposalRecord,
)
from app.runtime.timeline_runtime import TimelineRuntime
from app.session.enums import SessionLifecyclePhase, SessionScope
from app.session.identity import SessionId, SessionLineageId, as_session_id
from app.session.persistence import (
    PostgresSessionPersistence,
    SessionEventQuery,
    SessionRecord,
)
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]

_TENANT_ID = "tenant-acme"
_OTHER_TENANT_ID = "tenant-other"
_ACTION_ACTOR = "agent:diagnostic-action-orchestrator"
_NOW = datetime(2026, 5, 22, 13, tzinfo=timezone.utc)


@pytest.fixture
def pg_tenant_id() -> str:
    return _TENANT_ID


@pytest_asyncio.fixture
async def approval_client(
    pg_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[httpx.AsyncClient]:
    redis = _NoopRedis()
    monkeypatch.setattr(redis_module, "_redis_client", redis)
    monkeypatch.setattr(main_module, "get_redis_client", lambda: redis)
    monkeypatch.setattr(service_dependencies, "get_redis_client", lambda: redis)

    async def _executed_outcome(
        self: object,
        *,
        approval_record: ActionApprovalRecord,
        approved_decision_id: str,
        execution_context: object,
        expected_tenant_id: str,
    ) -> ActionOutcome:
        """Test double: consume grant + record event without a real connector."""
        await PostgresAgentActionGrantRepository(pg_session).consume_grant(
            decision_id=uuid.UUID(approved_decision_id),
            tenant_id=expected_tenant_id,
            actor=_ACTION_ACTOR,
        )
        dispatch_id = (
            approval_record.metadata.get("dispatch_id")
            or approval_record.execution_id
            or approval_record.approval_id
        )
        await TimelineRuntime(
            persistence=PostgresSessionPersistence(pg_session)
        ).append_event(
            session_id=approval_record.session_id,
            dispatch_id=dispatch_id,
            tenant_id=expected_tenant_id,
            event_type="action_executed",
            payload={
                "approval_id": approval_record.approval_id,
                "tool_name": approval_record.tool_name,
                "action_type": approval_record.metadata.get("action_type") or "unknown",
                "idempotency_key": approval_record.idempotency_key,
                "governance_decision_id": approved_decision_id,
                "result": {"status": "success"},
            },
            timestamp=datetime.now(timezone.utc),
            idempotency_key=f"action:approved-executed:{approval_record.idempotency_key}",
        )
        return ActionOutcome(
            tool_name=approval_record.tool_name,
            idempotency_key=approval_record.idempotency_key,
            status="executed",
            governance_decision_id=approved_decision_id,
            approval_record_id=approval_record.approval_id,
        )

    # Patch re_invoke_approved_action so the test doesn't need a real connector
    # config in the DB. The test verifies governance wiring, not connector execution.
    monkeypatch.setattr(
        ActionOrchestrationRuntime,
        "re_invoke_approved_action",
        _executed_outcome,
    )
    app = create_app()

    async def _override() -> AsyncIterator[AsyncSession]:
        yield pg_session

    app.dependency_overrides[get_db_session] = _override
    app.dependency_overrides[require_tenant_operations_read] = lambda: (
        AuthorityContext(
            tenant_id=_TENANT_ID,
            capabilities=("tenant.operations.read",),
        )
    )
    app.dependency_overrides[require_tenant_actions_approve] = lambda: (
        AuthorityContext(
            tenant_id=_TENANT_ID,
            capabilities=("tenant.actions.approve",),
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        yield client


def _headers(tenant: str = _TENANT_ID) -> dict[str, str]:
    return {"X-Tenant-ID": tenant, "X-Principal-ID": "principal-manager"}


def _ids(seed: str) -> dict[str, str]:
    return {
        "session_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{seed}:session")),
        "execution_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{seed}:execution")),
        "dispatch_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{seed}:dispatch")),
        "proposal_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{seed}:proposal")),
        "source_decision_id": str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"{seed}:source-decision")
        ),
        "idempotency_key": str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"{seed}:idempotency")
        ),
    }


def _session(*, ids: dict[str, str], tenant_id: str = _TENANT_ID) -> SessionRecord:
    sid = SessionId(uuid.UUID(ids["session_id"]))
    return SessionRecord(
        session_id=sid,
        scope=SessionScope.TENANT,
        external_handle="ticket-action-approval",
        tenant_id=tenant_id,
        principal_id="principal-agent",
        opened_at=_NOW,
        lifecycle_phase=SessionLifecyclePhase.ACTIVE,
        lifecycle_recorded_at=_NOW,
        lifecycle_reason=None,
        lineage_id=SessionLineageId(uuid.UUID(ids["session_id"])),
        root_session_id=sid,
        parent_session_id=None,
        ancestor_session_ids=(),
        lineage_depth=0,
        sequence_head=-1,
        revision=0,
    )


def _decision(
    *,
    ids: dict[str, str],
    tenant_id: str = _TENANT_ID,
) -> GovernanceDecisionRecord:
    return GovernanceDecisionRecord(
        decision_id=ids["source_decision_id"],
        decision=Decision.REQUIRE_APPROVAL.value,
        stage=EnforcementStage.PRE_EXECUTION.value,
        policy_chain_id="agent.action_tools.pre_execution",
        reason="refund exceeds auto-allow threshold",
        decided_at=_NOW.isoformat(),
        tenant_id=tenant_id,
        subject_kind="agent_action",
        metadata={"session_id": ids["session_id"]},
    )


def _proposal(
    *,
    ids: dict[str, str],
    tenant_id: str = _TENANT_ID,
) -> ResolutionProposalRecord:
    return ResolutionProposalRecord(
        proposal_id=ResolutionProposalId(uuid.UUID(ids["proposal_id"])),
        tenant_id=tenant_id,
        session_id=ids["session_id"],
        execution_id=ids["execution_id"],
        dispatch_id=ids["dispatch_id"],
        diagnostic_event_id=None,
        proposed_customer_reply="Product defect confirmed by diagnostic analysis.",
        resolution_category="product_defect",
        confidence=0.82,
        supervisor_verdict=ResolutionSupervisorVerdict.PASS,
        governance_verdict=ResolutionGovernanceVerdict.REQUIRE_APPROVAL,
        autonomy_decision=ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL,
        status=ResolutionProposalStatus.PENDING_HUMAN_APPROVAL,
        created_at=_NOW,
        updated_at=_NOW,
        governance_decision_id=uuid.UUID(ids["source_decision_id"]),
        recommended_actions=(
            {
                "type": "warranty_claim",
                "requires_execution": True,
                "tool_name": "warranty.claim",
            },
        ),
        evidence=(),
    )


def _payload() -> dict[str, object]:
    return {
        "order_id": "order-100",
        "product_sku": "A1771",
        "issue_category": "product_defect",
        "customer_description": "Unit fails under confirmed warranty.",
    }


async def _ensure_tenant(pg_session: AsyncSession, tenant_id: str) -> None:
    await pg_session.execute(
        text(
            """
            INSERT INTO public.tenants (tenant_id)
            VALUES (:tenant_id)
            ON CONFLICT (tenant_id) DO NOTHING
            """
        ),
        {"tenant_id": tenant_id},
    )


async def _seed_base(
    pg_session: AsyncSession,
    *,
    seed: str,
    tenant_id: str = _TENANT_ID,
) -> dict[str, str]:
    ids = _ids(seed)
    await _ensure_tenant(pg_session, tenant_id)
    sessions = PostgresSessionPersistence(pg_session)
    await sessions.save_session(_session(ids=ids, tenant_id=tenant_id))
    await pg_session.execute(
        text(
            """
            INSERT INTO public.execution_records (
                execution_id, kind, dispatch_id, session_id, tenant_id,
                state, attempt_count, requested_at, result, metadata
            )
            VALUES (
                :execution_id, 'diagnostic_agent', :dispatch_id,
                :session_id, :tenant_id, 'requested', 0,
                :requested_at, '{}'::jsonb, '{}'::jsonb
            )
            ON CONFLICT (tenant_id, dispatch_id, kind) DO NOTHING
            """
        ),
        {
            "execution_id": uuid.UUID(ids["execution_id"]),
            "dispatch_id": ids["dispatch_id"],
            "session_id": ids["session_id"],
            "tenant_id": tenant_id,
            "requested_at": _NOW,
        },
    )
    await TimelineRuntime(persistence=sessions).append_event(
        session_id=ids["session_id"],
        dispatch_id=ids["dispatch_id"],
        tenant_id=tenant_id,
        event_type="diagnostic_analysis_completed",
        payload={
            "classification_category": "product_defect",
            "classification_confidence": 0.82,
            "classification_summary": "Warranty defect with replacement path.",
        },
        timestamp=_NOW,
        idempotency_key=f"diagnostic:{seed}",
    )
    await PostgresGovernanceRepository(pg_session).record_decision(
        _decision(ids=ids, tenant_id=tenant_id)
    )
    await PostgresResolutionProposalPersistence(pg_session).create_resolution_proposal(
        _proposal(ids=ids, tenant_id=tenant_id),
        expected_tenant_id=tenant_id,
    )
    return ids


async def _create_approval(
    pg_session: AsyncSession,
    *,
    seed: str,
    tenant_id: str = _TENANT_ID,
    status: str = "pending",
) -> ActionApprovalRecord:
    ids = await _seed_base(pg_session, seed=seed, tenant_id=tenant_id)
    repo = PostgresActionApprovalRepository(pg_session)
    approval = await repo.create_pending_approval(
        build_pending_action_approval(
            tenant_id=tenant_id,
            session_id=ids["session_id"],
            execution_id=ids["execution_id"],
            tool_name="warranty.claim",
            idempotency_key=ids["idempotency_key"],
            payload_json=_payload(),
            governance_decision_id=ids["source_decision_id"],
            metadata={
                "proposal_id": ids["proposal_id"],
                "action_type": "warranty_claim",
                "target_resource": "order:order-100:sku:A1771",
                AGENT_ACTION_ACTOR_KEY: _ACTION_ACTOR,
            },
        ),
        expected_tenant_id=tenant_id,
    )
    if status == "pending":
        return approval
    resolved = await repo.resolve_approval(
        approval.approval_id,
        expected_tenant_id=tenant_id,
        status=status,
        resolved_at=_NOW,
        resolved_by="principal-manager",
        resolution_note=status,
        metadata=dict(approval.metadata),
    )
    assert resolved is not None
    return resolved


async def _events(
    pg_session: AsyncSession,
    approval: ActionApprovalRecord,
) -> tuple[object, ...]:
    page = await PostgresSessionPersistence(pg_session).list_events(
        SessionEventQuery(
            session_id=as_session_id(approval.session_id),
            limit=100,
        ),
        expected_tenant_id=approval.tenant_id,
    )
    return tuple(page.events)


def _event_payload(event: object) -> dict[str, object]:
    payload = getattr(event, "payload")
    assert isinstance(payload, dict)
    nested = payload.get("payload")
    assert isinstance(nested, dict)
    return nested


@pytest.mark.asyncio
async def test_list_pending_returns_only_pending(
    approval_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    await _create_approval(pg_session, seed="list-pending-a")
    await _create_approval(pg_session, seed="list-pending-b")
    await _create_approval(pg_session, seed="list-approved", status="approved")
    await _create_approval(pg_session, seed="list-denied", status="denied")

    response = await approval_client.get(
        "/api/v1/approvals/actions",
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()["items"]
    assert len(body) == 2
    assert {record["status"] for record in body} == {"pending"}


@pytest.mark.asyncio
async def test_get_with_context_returns_joined_data(
    approval_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    approval = await _create_approval(pg_session, seed="detail-context")

    response = await approval_client.get(
        f"/api/v1/approvals/actions/{approval.approval_id}",
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["approval_id"] == approval.approval_id
    assert body["classification_category"] == "product_defect"
    assert body["classification_confidence"] == 0.82
    assert body["governance_decision_id"] == approval.governance_decision_id
    assert body["governance_reason"] == "refund exceeds auto-allow threshold"


@pytest.mark.asyncio
async def test_approve_creates_governance_decision(
    approval_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    approval = await _create_approval(pg_session, seed="approve-governance")

    response = await approval_client.post(
        f"/api/v1/approvals/actions/{approval.approval_id}/approve",
        headers=_headers(),
        json={"note": "approved by manager"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    decision_id = body["metadata"]["manager_governance_decision_id"]
    manager_decision = await PostgresGovernanceRepository(pg_session).get_decision(
        decision_id,
        expected_tenant_id=_TENANT_ID,
    )
    assert manager_decision is not None
    assert manager_decision.decision == Decision.ALLOW.value
    assert manager_decision.subject_kind == "manager_approval"
    assert manager_decision.metadata[AGENT_ACTION_BINDING_KEY] == (
        compute_agent_action_binding(
            tenant_id=approval.tenant_id,
            tool_name=approval.tool_name,
            actor=_ACTION_ACTOR,
            payload=dict(approval.payload_json),
        )
    )
    assert manager_decision.metadata[AGENT_ACTION_ACTOR_KEY] == _ACTION_ACTOR

    grant = (
        await pg_session.execute(
            text(
                """
                SELECT actor, binding_hash, consumed_by
                FROM public.agent_action_grants
                WHERE decision_id = CAST(:decision_id AS uuid)
                  AND tenant_id = :tenant_id
                """
            ),
            {"decision_id": decision_id, "tenant_id": _TENANT_ID},
        )
    ).mappings().one()
    assert grant["actor"] == _ACTION_ACTOR
    assert grant["binding_hash"] == manager_decision.metadata[AGENT_ACTION_BINDING_KEY]
    assert grant["consumed_by"] == _ACTION_ACTOR

    executed = [
        event for event in await _events(pg_session, approval)
        if getattr(event, "annotation") == "action_executed"
    ]
    assert len(executed) == 1
    assert _event_payload(executed[0])["governance_decision_id"] == decision_id


@pytest.mark.asyncio
async def test_approve_invokes_tool_via_tool_invoker(
    approval_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    approval = await _create_approval(pg_session, seed="approve-invokes-tool")

    response = await approval_client.post(
        f"/api/v1/approvals/actions/{approval.approval_id}/approve",
        headers=_headers(),
        json={"note": "execute approved action"},
    )

    assert response.status_code == 200
    body = response.json()
    decision_id = body["metadata"]["manager_governance_decision_id"]
    executed = [
        event for event in await _events(pg_session, approval)
        if getattr(event, "annotation") == "action_executed"
    ]
    assert len(executed) == 1
    payload = _event_payload(executed[0])
    assert payload["governance_decision_id"] == decision_id
    assert payload["result"]["status"] == "success"


@pytest.mark.asyncio
async def test_deny_creates_no_governance_decision(
    approval_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    approval = await _create_approval(pg_session, seed="deny-no-governance")
    governance = PostgresGovernanceRepository(pg_session)
    before = await governance.query_decisions(
        DecisionQuery(tenant_id=_TENANT_ID, subject_kind="manager_approval")
    )

    response = await approval_client.post(
        f"/api/v1/approvals/actions/{approval.approval_id}/deny",
        headers=_headers(),
        json={"reason": "manager declined action"},
    )

    after = await governance.query_decisions(
        DecisionQuery(tenant_id=_TENANT_ID, subject_kind="manager_approval")
    )
    assert response.status_code == 200
    assert response.json()["status"] == "denied"
    assert after.total == before.total
    denied = [
        event for event in await _events(pg_session, approval)
        if getattr(event, "annotation") == "action_denied"
    ]
    assert len(denied) == 1
    assert _event_payload(denied[0])["reason"] == "manager declined action"


@pytest.mark.asyncio
async def test_deny_twice_fails(
    approval_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    approval = await _create_approval(pg_session, seed="deny-twice")
    first = await approval_client.post(
        f"/api/v1/approvals/actions/{approval.approval_id}/deny",
        headers=_headers(),
        json={"reason": "not needed"},
    )
    second = await approval_client.post(
        f"/api/v1/approvals/actions/{approval.approval_id}/deny",
        headers=_headers(),
        json={"reason": "again"},
    )

    assert first.status_code == 200
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_approval_cross_tenant_blocked(
    approval_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    approval = await _create_approval(pg_session, seed="tenant-blocked")

    own = await approval_client.get(
        "/api/v1/approvals/actions",
        headers=_headers(_TENANT_ID),
    )
    other = await approval_client.get(
        "/api/v1/approvals/actions",
        headers=_headers(_OTHER_TENANT_ID),
    )
    detail_cross = await approval_client.get(
        f"/api/v1/approvals/actions/{approval.approval_id}",
        headers=_headers(_OTHER_TENANT_ID),
    )

    assert own.status_code == 200
    assert len(own.json()["items"]) == 1
    assert other.status_code == 200
    assert other.json()["items"] == []
    assert detail_cross.status_code == 404


class _NoopRedis:
    async def aclose(self) -> None:
        return None

    async def config_get(self, _name: str) -> dict[str, str]:
        return {"maxmemory-policy": "allkeys-lru"}

    async def eval(self, *_args: object) -> int:
        return 1

    async def get(self, _key: str) -> None:
        return None

    async def info(self, _section: str) -> dict[str, int]:
        return {"used_memory": 0, "maxmemory": 0}

    async def llen(self, _key: str) -> int:
        return 0

    async def ping(self) -> bool:
        return True

    def pubsub(self) -> "_NoopRedis":
        return self

    async def set(
        self,
        _key: str,
        _value: str,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool:
        del nx, ex
        return True

    async def zadd(self, *_args: object, **_kwargs: object) -> int:
        return 1

    async def zrange(self, *_args: object, **_kwargs: object) -> list[object]:
        return []

    async def zremrangebyscore(self, *_args: object, **_kwargs: object) -> int:
        return 0
