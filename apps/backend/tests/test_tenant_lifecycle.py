"""Platform-gated tenant lifecycle tests (2.5c)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from inspect import signature
from types import SimpleNamespace
from typing import cast

from fastapi import HTTPException
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.agents.tools.action_governance import (
    ACTION_TOOLS_POLICY_TYPE,
    TenantActionPolicy,
)
from app.auth.providers.jwt import (
    DEFAULT_CLAIM_MAPPING,
    extract_capabilities_from_claims,
)
from app.api.v1.routers.tenant import create_tenant_lifecycle
from app.api.v1.schemas.tenant import TenantLifecycleCreateRequest
from app.dependencies.authority import (
    OPERATOR_CAPABILITY,
    PLATFORM_TENANT_ADMIN_CAPABILITY,
    TENANT_CONFIG_APPROVE_CAPABILITY,
    TENANT_CONFIG_DOMAIN_WRITE_CAPABILITIES,
    TENANT_CONFIG_READ_CAPABILITY,
    require_platform_tenant_admin,
)
from app.events import OperationalEventQuery, PostgresOperationalEventPersistence
from app.events.appender import OperationalEventAppender
from app.governance.capability.acts import OperationalAct
from app.governance.context import GovernanceContext
from app.governance.enums import Decision, EnforcementStage
from app.governance.subjects import AgentActionGovernanceSubject
from app.identity import AuthorityContext, TenantId
from app.services.tenant_lifecycle_service import TenantLifecycleService
from app.tenant.enums import TenantStatus
from app.tenant.lifecycle import (
    PostgresTenantLifecycleRepository,
    TenantAlreadyExistsError,
    TenantLifecyclePage,
    TenantLifecycleRecord,
)
from app.tenant.persistence import (
    PostgresTenantConfigurationRepository,
    TenantChannelConfigurationQuery,
    TenantConnectorConfigurationQuery,
    TenantGovernancePolicyQuery,
)
from tests.conftest import set_pg_rls_tenant

_NOW = datetime(2026, 6, 4, tzinfo=timezone.utc)
_ROUTE_TENANT_ID = "tenant-lifecycle-route"


class _FakeTenantLifecycleService:
    def __init__(self) -> None:
        self.created: list[tuple[str, str]] = []
        self.records: list[TenantLifecycleRecord] = []

    async def create_tenant(
        self,
        *,
        tenant_id: str,
        created_by: str,
    ) -> TenantLifecycleRecord:
        self.created.append((tenant_id, created_by))
        record = TenantLifecycleRecord(
            tenant_id=tenant_id,
            status=TenantStatus.ACTIVE,
            created_at=_NOW,
        )
        self.records.append(record)
        return record

    async def list_tenants(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> TenantLifecyclePage:
        return TenantLifecyclePage(
            items=tuple(self.records[offset : offset + limit]),
            total=len(self.records),
            limit=limit,
            offset=offset,
        )


@pytest.mark.asyncio
async def test_2_5c_1_platform_capability_required() -> None:
    route_authority_dependency = (
        signature(create_tenant_lifecycle)
        .parameters["authority"]
        .default
        .dependency
    )
    operator_request = _request(
        AuthorityContext.from_raw(
            tenant_id="tenant-acme",
            principal_id="operator-principal",
            capabilities=frozenset(
                {
                    OPERATOR_CAPABILITY,
                    *TENANT_CONFIG_DOMAIN_WRITE_CAPABILITIES,
                    TENANT_CONFIG_READ_CAPABILITY,
                    TENANT_CONFIG_APPROVE_CAPABILITY,
                }
            ),
        )
    )
    platform_authority = require_platform_tenant_admin(
        _request(
            AuthorityContext.from_raw(
                principal_id="platform-principal",
                capabilities=frozenset({PLATFORM_TENANT_ADMIN_CAPABILITY}),
            )
        )
    )
    service = _FakeTenantLifecycleService()

    with pytest.raises(HTTPException) as denied:
        require_platform_tenant_admin(operator_request)
    response = await create_tenant_lifecycle(
        TenantLifecycleCreateRequest(tenant_id=_ROUTE_TENANT_ID),
        authority=platform_authority,
        service=cast(TenantLifecycleService, service),
    )

    assert route_authority_dependency is require_platform_tenant_admin
    assert denied.value.status_code == 403
    assert denied.value.detail == {
        "code": "capability_required",
        "capability": PLATFORM_TENANT_ADMIN_CAPABILITY,
    }
    assert response.tenant_id == _ROUTE_TENANT_ID
    assert service.created == [(_ROUTE_TENANT_ID, "platform-principal")]


def test_2_5c_5_platform_capability_is_not_in_tenant_bundles() -> None:
    operator = _capabilities_for_roles("Operator")
    tenant_admin = _capabilities_for_roles("TenantAdmin")
    approver = _capabilities_for_roles("TenantApprover")
    platform = _capabilities_for_roles("PlatformAdmin")

    assert PLATFORM_TENANT_ADMIN_CAPABILITY not in operator
    assert PLATFORM_TENANT_ADMIN_CAPABILITY not in tenant_admin
    assert PLATFORM_TENANT_ADMIN_CAPABILITY not in approver
    assert platform == frozenset({PLATFORM_TENANT_ADMIN_CAPABILITY})


@pytest.mark.asyncio
async def test_2_5c_2_created_tenant_is_inert(
    pg_session: AsyncSession,
) -> None:
    tenant_id = _tenant("inert")
    service = _service(pg_session)

    await service.create_tenant(
        tenant_id=tenant_id,
        created_by="platform-principal",
    )
    await set_pg_rls_tenant(pg_session, tenant_id)
    repo = PostgresTenantConfigurationRepository(pg_session)

    channels = await repo.list_channel_configurations(
        TenantChannelConfigurationQuery(),
        expected_tenant_id=tenant_id,
    )
    connectors = await repo.list_connector_configurations(
        TenantConnectorConfigurationQuery(),
        expected_tenant_id=tenant_id,
    )
    policies = await repo.list_governance_policies(
        TenantGovernancePolicyQuery(),
        expected_tenant_id=tenant_id,
    )
    action_policy = await repo.resolve_active_governance_policy(
        policy_type=ACTION_TOOLS_POLICY_TYPE,
        expected_tenant_id=tenant_id,
    )
    decision = (
        await TenantActionPolicy(repository=repo).evaluate(
            _action_context(tenant_id)
        )
    )[0]

    assert channels.total == 0
    assert connectors.total == 0
    assert policies.total == 0
    assert action_policy is None
    assert decision.decision is Decision.DENY
    assert "no active" in decision.reason


@pytest.mark.asyncio
async def test_2_5c_3_creation_is_audited(
    pg_session: AsyncSession,
) -> None:
    tenant_id = _tenant("audit")

    await _service(pg_session).create_tenant(
        tenant_id=tenant_id,
        created_by="platform-auditor",
    )
    page = await _tenant_create_events(pg_session, tenant_id)

    assert page.total == 1
    event = page.events[0]
    assert event.operational_act is OperationalAct.TENANT_CREATE
    assert event.tenant_id == tenant_id
    assert event.principal_id == "platform-auditor"
    assert event.metadata["projection_source"] == "tenant_lifecycle"
    assert event.metadata["operation"] == "create"


@pytest.mark.asyncio
async def test_2_5c_4_duplicate_create_rejected_without_duplicate_event(
    pg_session: AsyncSession,
) -> None:
    tenant_id = _tenant("duplicate")
    service = _service(pg_session)

    await service.create_tenant(
        tenant_id=tenant_id,
        created_by="platform-principal",
    )
    with pytest.raises(TenantAlreadyExistsError):
        await service.create_tenant(
            tenant_id=tenant_id,
            created_by="platform-principal",
        )
    page = await _tenant_create_events(pg_session, tenant_id)

    assert page.total == 1


@pytest.mark.asyncio
async def test_platform_admin_can_list_tenants_without_tenant_axis(
    pg_session: AsyncSession,
) -> None:
    service = _service(pg_session)
    tenant_a = f"000-tenant-lifecycle-list-a-{uuid.uuid4()}"
    tenant_b = f"000-tenant-lifecycle-list-b-{uuid.uuid4()}"

    await service.create_tenant(tenant_id=tenant_a, created_by="platform")
    await service.create_tenant(tenant_id=tenant_b, created_by="platform")
    page = await service.list_tenants(limit=100, offset=0)

    listed = {record.tenant_id for record in page.items}
    assert {tenant_a, tenant_b}.issubset(listed)


def _capabilities_for_roles(*roles: str) -> frozenset[str]:
    return extract_capabilities_from_claims(
        claims={"sub": "principal-test", "roles": list(roles)},
        claim_mapping=DEFAULT_CLAIM_MAPPING,
    )


def _request(authority: AuthorityContext) -> Request:
    return cast(Request, SimpleNamespace(state=SimpleNamespace(authority=authority)))


def _service(session: AsyncSession) -> TenantLifecycleService:
    return TenantLifecycleService(
        repository=PostgresTenantLifecycleRepository(session),
        event_appender=OperationalEventAppender(
            persistence=PostgresOperationalEventPersistence(session)
        ),
        session=session,
    )


def _tenant(label: str) -> str:
    return f"tenant-lifecycle-{label}-{uuid.uuid4()}"


def _action_context(tenant_id: str) -> GovernanceContext:
    return GovernanceContext(
        stage=EnforcementStage.PRE_EXECUTION,
        action="tool.invoke",
        resource="tool:refund.request",
        actor="agent:test",
        tenant_id=TenantId(tenant_id),
        subject=AgentActionGovernanceSubject(
            agent_id="test-agent",
            capability="tool.refund.request",
            tool_name="refund.request",
            target_resource="refund:order-1",
            execution_scope=f"tenant:{tenant_id}",
            tenant_id=tenant_id,
            metadata={
                "tool_name": "refund.request",
                "refund_amount_cents": 1000,
            },
        ),
    )


async def _tenant_create_events(
    session: AsyncSession,
    tenant_id: str,
):
    await set_pg_rls_tenant(session, tenant_id)
    return await PostgresOperationalEventPersistence(session).list_events(
        OperationalEventQuery(
            tenant_id=tenant_id,
            operational_act=OperationalAct.TENANT_CREATE,
        ),
        expected_tenant_id=tenant_id,
    )
