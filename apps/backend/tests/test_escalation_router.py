"""Phase 3-C escalation queue endpoint tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.authority import (
    require_tenant_actions_approve,
    require_tenant_operations_read,
)
from app.dependencies.database import get_db_session
from app.escalation import (
    EscalationHandoffKind,
    EscalationPriority,
    EscalationStatus,
    derive_escalation_id,
)
from app.escalation.persistence import (
    EscalationRecord,
    PostgresEscalationPersistence,
)
from app.governance.persistence import (
    GovernanceDecisionRecord,
    PostgresGovernanceRepository,
)
from app.identity import AuthorityContext
from app.main import create_app
from app.session.enums import SessionLifecyclePhase, SessionScope
from app.session.identity import SessionId, SessionLineageId
from app.session.persistence import PostgresSessionPersistence, SessionRecord
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]

_NOW = datetime(2026, 5, 22, 13, tzinfo=timezone.utc)
_SESSION_ID = "00000000-0000-0000-0000-000000003e01"
_DENY_ID = "00000000-0000-0000-0000-000000003e02"
_ESCALATE_ID = "00000000-0000-0000-0000-000000003e03"
_CRISIS_DENY_ID = "00000000-0000-0000-0000-000000003e04"


@pytest.fixture
def pg_tenant_id() -> str:
    return "tenant-acme"


@pytest_asyncio.fixture
async def escalation_client(
    pg_session: AsyncSession,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()

    async def _override() -> AsyncIterator[AsyncSession]:
        yield pg_session

    app.dependency_overrides[get_db_session] = _override
    app.dependency_overrides[require_tenant_operations_read] = lambda: (
        AuthorityContext(
            tenant_id="tenant-acme",
            capabilities=("tenant.operations.read",),
        )
    )
    app.dependency_overrides[require_tenant_actions_approve] = lambda: (
        AuthorityContext(
            tenant_id="tenant-acme",
            capabilities=("tenant.actions.approve",),
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        yield client


def _headers(tenant: str = "tenant-acme") -> dict[str, str]:
    return {"X-Tenant-ID": tenant, "X-Principal-ID": "principal-manager"}


def _session() -> SessionRecord:
    sid = SessionId(uuid.UUID(_SESSION_ID))
    return SessionRecord(
        session_id=sid,
        scope=SessionScope.TENANT,
        external_handle="ticket-router",
        tenant_id="tenant-acme",
        principal_id="principal-agent",
        opened_at=_NOW,
        lifecycle_phase=SessionLifecyclePhase.ACTIVE,
        lifecycle_recorded_at=_NOW,
        lifecycle_reason=None,
        lineage_id=SessionLineageId(uuid.UUID(_SESSION_ID)),
        root_session_id=sid,
        parent_session_id=None,
        ancestor_session_ids=(),
        lineage_depth=0,
        sequence_head=0,
        revision=1,
    )


def _decision(
    *,
    decision_id: str = _DENY_ID,
    decision: str = "deny",
    reason: str = "deny",
) -> GovernanceDecisionRecord:
    return GovernanceDecisionRecord(
        decision_id=decision_id,
        decision=decision,
        stage="pre_execution",
        policy_chain_id="router.chain",
        reason=reason,
        decided_at=_NOW.isoformat(),
        tenant_id="tenant-acme",
        metadata={"session_id": _SESSION_ID},
    )


def _record(
    *,
    governance_decision_id: str = _DENY_ID,
    reason: str = "deny",
    handoff_kind: str = EscalationHandoffKind.DENIAL.value,
    priority: str = EscalationPriority.NORMAL.value,
    metadata: dict[str, object] | None = None,
) -> EscalationRecord:
    return EscalationRecord(
        escalation_id=str(
            derive_escalation_id(
                tenant_id="tenant-acme",
                session_id=_SESSION_ID,
                governance_decision_id=governance_decision_id,
            )
        ),
        session_id=_SESSION_ID,
        tenant_id="tenant-acme",
        reason=reason,
        governance_decision_id=governance_decision_id,
        status=EscalationStatus.PENDING.value,
        created_at=_NOW.isoformat(),
        handoff_kind=handoff_kind,
        priority=priority,
        metadata=metadata or {},
    )


async def _seed(pg_session: AsyncSession) -> EscalationRecord:
    await PostgresSessionPersistence(pg_session).save_session(_session())
    await PostgresGovernanceRepository(pg_session).record_decision(
        _decision()
    )
    record = _record()
    await PostgresEscalationPersistence(pg_session).create_escalation(
        record,
        expected_tenant_id="tenant-acme",
    )
    return record


@pytest.mark.asyncio
async def test_escalation_queue_endpoints_are_tenant_scoped(
    escalation_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    record = await _seed(pg_session)

    own = await escalation_client.get(
        "/api/v1/escalations",
        headers=_headers("tenant-acme"),
    )
    other = await escalation_client.get(
        "/api/v1/escalations",
        headers=_headers("tenant-other"),
    )
    point_cross = await escalation_client.get(
        f"/api/v1/escalations/{record.escalation_id}",
        headers=_headers("tenant-other"),
    )

    assert own.status_code == 200
    assert own.json()["total"] == 1
    item = own.json()["items"][0]
    assert item["handoff_kind"] == "denial"
    assert item["priority"] == "normal"
    assert item["source_decision"] is None
    assert other.status_code == 200
    assert other.json()["total"] == 0
    assert point_cross.status_code == 404


@pytest.mark.asyncio
async def test_manager_approval_endpoint_creates_override_record(
    escalation_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    record = await _seed(pg_session)

    response = await escalation_client.post(
        f"/api/v1/escalations/{record.escalation_id}/approve",
        headers=_headers("tenant-acme"),
        json={"resolution": "approve one-time exception"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["resolved_by"] == "principal-manager"
    assert body["governance_override_decision_id"] is not None
    override = await PostgresGovernanceRepository(pg_session).get_decision(
        body["governance_override_decision_id"],
        expected_tenant_id="tenant-acme",
    )
    assert override is not None
    assert override.decision == "allow"


@pytest.mark.asyncio
async def test_manager_rejection_endpoint_keeps_denial_lineage(
    escalation_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    record = await _seed(pg_session)

    response = await escalation_client.post(
        f"/api/v1/escalations/{record.escalation_id}/reject",
        headers=_headers("tenant-acme"),
        json={"resolution": "denial stands"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert body["governance_override_decision_id"] is None
    denied = await PostgresGovernanceRepository(pg_session).get_decision(
        _DENY_ID,
        expected_tenant_id="tenant-acme",
    )
    assert denied is not None
    assert denied.decision == "deny"


@pytest.mark.asyncio
async def test_approve_endpoint_refuses_escalate_handoff(
    escalation_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    await PostgresSessionPersistence(pg_session).save_session(_session())
    governance = PostgresGovernanceRepository(pg_session)
    await governance.record_decision(
        _decision(
            decision_id=_ESCALATE_ID,
            decision="escalate",
            reason="escalate: crisis all",
        )
    )
    persistence = PostgresEscalationPersistence(pg_session)
    escalated = _record(
        governance_decision_id=_ESCALATE_ID,
        reason="escalate: crisis all",
        handoff_kind=EscalationHandoffKind.ESCALATION.value,
        priority=EscalationPriority.HIGH.value,
        metadata={
            "source_decision": "escalate",
            "handoff_kind": "escalation",
            "priority": "high",
        },
    )
    await persistence.create_escalation(
        escalated,
        expected_tenant_id="tenant-acme",
    )

    approve = await escalation_client.post(
        f"/api/v1/escalations/{escalated.escalation_id}/approve",
        headers=_headers("tenant-acme"),
        json={"resolution": "should not override escalate"},
    )

    assert approve.status_code == 400
    assert "escalation_approval_failed" in approve.json()["detail"]


@pytest.mark.asyncio
async def test_reject_endpoint_refuses_crisis_handoff(
    escalation_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    await PostgresSessionPersistence(pg_session).save_session(_session())
    await PostgresGovernanceRepository(pg_session).record_decision(
        _decision(
            decision_id=_CRISIS_DENY_ID,
            decision="deny",
            reason="crisis:block_sku denied",
        )
    )
    crisis = _record(
        governance_decision_id=_CRISIS_DENY_ID,
        reason="crisis:block_sku denied",
        handoff_kind=EscalationHandoffKind.CRISIS.value,
        priority=EscalationPriority.HIGH.value,
        metadata={
            "source_decision": "deny",
            "handoff_kind": "crisis",
            "priority": "high",
            "crisis": True,
            "crisis_policy": "crisis.block_sku",
        },
    )
    await PostgresEscalationPersistence(pg_session).create_escalation(
        crisis,
        expected_tenant_id="tenant-acme",
    )
    reject = await escalation_client.post(
        f"/api/v1/escalations/{crisis.escalation_id}/reject",
        headers=_headers("tenant-acme"),
        json={"resolution": "should not reject crisis"},
    )

    assert reject.status_code == 400
    assert "escalation_rejection_failed" in reject.json()["detail"]
