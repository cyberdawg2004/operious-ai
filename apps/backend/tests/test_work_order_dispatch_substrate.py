"""Phase 2.3.x-a work-order dispatch substrate break-controls."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import ClassVar

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import (
    AgentCapability,
    CapabilitySet,
    ExecutionConstraints,
)
from app.agents.context import AgentExecutionContext
from app.agents.envelopes import ToolInvocationEnvelope
from app.agents.enums import CapabilityScope
from app.agents.identity import AgentIdentity, ExecutionIdentity
from app.agents.results import ToolInvocationRequest, ToolInvocationResult
from app.agents.tools import BaseTool, ToolCapability, ToolInvoker, ToolRegistry
from app.agents.tools.action_governance import (
    ACTION_TOOLS_POLICY_TYPE,
    build_action_tool_governance_runtime,
)
from app.agents.value_objects import CausalityMetadata
from app.governance.enums import Decision
from app.governance.persistence.memory import InMemoryGovernanceRepository
from app.session.enums import SessionLifecyclePhase
from app.tenant.chronology import canonical_sha256
from app.tenant.db.models import TenantRow
from app.tenant.enums import TenantGovernancePolicyStatus
from app.tenant.identity import derive_governance_policy_version_id
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    TenantGovernancePolicyRecord,
)
from app.work_orders.enums import WorkOrderState
from app.work_orders.exceptions import WorkOrderStateTransitionError
from app.work_orders.identity import derive_work_order_id
from app.work_orders.persistence import (
    PostgresWorkOrderRepository,
    WorkOrderRecord,
)
from app.work_orders.state_machine import assert_transition
from tests.conftest import requires_postgres, set_pg_rls_tenant

pytestmark = pytest.mark.asyncio

_NOW = datetime(2026, 6, 5, tzinfo=timezone.utc)
_TENANT_A = "tenant-work-order-a"
_TENANT_B = "tenant-work-order-b"
_CONTENT_SHA = "a" * 64
_SOURCE_APPROVAL_ID = "approval-work-order-config"


@requires_postgres
async def test_2_3_x_a_1_work_order_ledger_forces_tenant_rls(
    pg_session: AsyncSession,
) -> None:
    await _seed_tenants(pg_session, _TENANT_A, _TENANT_B)
    repo = PostgresWorkOrderRepository(pg_session)
    await set_pg_rls_tenant(pg_session, _TENANT_A)
    tenant_a = await repo.create_work_order(
        _record(_TENANT_A, seed="tenant-a"),
        expected_tenant_id=_TENANT_A,
    )
    await set_pg_rls_tenant(pg_session, _TENANT_B)
    tenant_b = await repo.create_work_order(
        _record(_TENANT_B, seed="tenant-b"),
        expected_tenant_id=_TENANT_B,
    )
    await pg_session.flush()

    try:
        await pg_session.execute(text("SET LOCAL ROLE operious_app_test"))
        await set_pg_rls_tenant(pg_session, _TENANT_A)
        visible = (
            await pg_session.execute(
                text(
                    """
                    SELECT tenant_id, work_order_id
                    FROM public.work_order_records
                    ORDER BY tenant_id, work_order_id
                    """
                )
            )
        ).all()
        assert visible == [(_TENANT_A, uuid.UUID(str(tenant_a.work_order_id)))]

        with pytest.raises(SQLAlchemyError):
            async with pg_session.begin_nested():
                await pg_session.execute(
                    text(
                        """
                        INSERT INTO public.work_order_records (
                            work_order_id,
                            tenant_id,
                            action_type,
                            tool_name,
                            connector_type,
                            connector_config_version,
                            connector_config_content_sha256,
                            connector_config_source_approval_id,
                            idempotency_key,
                            target_resource,
                            state
                        )
                        VALUES (
                            :work_order_id,
                            :tenant_id,
                            :action_type,
                            :tool_name,
                            :connector_type,
                            :connector_config_version,
                            :content_sha256,
                            :source_approval_id,
                            :idempotency_key,
                            :target_resource,
                            'created'
                        )
                        """
                    ),
                    {
                        "work_order_id": uuid.UUID(str(tenant_b.work_order_id)),
                        "tenant_id": _TENANT_B,
                        "action_type": "repair.dispatch",
                        "tool_name": "repair.dispatch",
                        "connector_type": "generic_rest_work_order",
                        "connector_config_version": 1,
                        "content_sha256": _CONTENT_SHA,
                        "source_approval_id": _SOURCE_APPROVAL_ID,
                        "idempotency_key": "cross-tenant-insert",
                        "target_resource": "repair:cross-tenant",
                    },
                )
    finally:
        await pg_session.execute(text("RESET ROLE"))


async def test_2_3_x_a_2_illegal_work_order_state_transition_rejected() -> None:
    assert_transition(WorkOrderState.CREATED, WorkOrderState.DISPATCHED)
    assert_transition(
        WorkOrderState.DISPATCHED,
        WorkOrderState.AWAITING_FULFILLMENT,
    )

    with pytest.raises(WorkOrderStateTransitionError):
        assert_transition(WorkOrderState.CREATED, WorkOrderState.FULFILLED)

    with pytest.raises(WorkOrderStateTransitionError):
        assert_transition(WorkOrderState.FULFILLED, WorkOrderState.DISPATCHED)


@requires_postgres
async def test_2_3_x_a_3_work_order_reconstruction_binding_round_trips(
    pg_session: AsyncSession,
) -> None:
    await _seed_tenants(pg_session, _TENANT_A)
    await set_pg_rls_tenant(pg_session, _TENANT_A)
    repo = PostgresWorkOrderRepository(pg_session)
    created = await repo.create_work_order(
        _record(_TENANT_A, seed="reconstruction", connector_version=3),
        expected_tenant_id=_TENANT_A,
    )

    loaded = await repo.get_work_order(
        created.work_order_id,
        expected_tenant_id=_TENANT_A,
    )

    assert loaded is not None
    assert loaded.connector_config_version == 3
    assert loaded.connector_config_content_sha256 == _CONTENT_SHA
    assert loaded.connector_config_source_approval_id == _SOURCE_APPROVAL_ID
    assert loaded.connector_config_content_sha256
    assert loaded.connector_config_source_approval_id


async def test_2_3_x_a_4_dispatch_governance_vocabulary_is_fail_closed() -> None:
    tenant_repository = InMemoryTenantConfigurationRepository()

    denied = await _invoke_repair_dispatch(
        tenant_id="tenant-no-dispatch-policy",
        tenant_repository=tenant_repository,
        seed="missing-policy",
    )

    assert denied.is_denied
    assert denied.trace.metadata["governance_decision"] == Decision.DENY.value

    await _save_action_policy(
        tenant_repository,
        tenant_id="tenant-dispatch-configured",
        repair_dispatch_decision="allow",
    )
    allowed = await _invoke_repair_dispatch(
        tenant_id="tenant-dispatch-configured",
        tenant_repository=tenant_repository,
        seed="configured-policy",
    )

    assert allowed.is_ok


async def test_2_3_x_a_5_work_order_states_are_not_session_lifecycle() -> None:
    assert {phase.value for phase in SessionLifecyclePhase} == {
        "initiated",
        "active",
        "dormant",
        "terminated",
        "archived",
    }
    lifecycle_values = {phase.value for phase in SessionLifecyclePhase}
    assert WorkOrderState.DISPATCHED.value not in lifecycle_values
    assert WorkOrderState.AWAITING_FULFILLMENT.value not in lifecycle_values
    assert WorkOrderState.FULFILLED.value not in lifecycle_values
    assert WorkOrderState.FAILED.value not in lifecycle_values


async def test_work_order_id_is_deterministic_uuid5() -> None:
    first = derive_work_order_id(
        tenant_id="tenant-deterministic-work-order",
        action_type="repair.dispatch",
        idempotency_key="idempotency-deterministic-work-order",
    )
    second = derive_work_order_id(
        tenant_id="tenant-deterministic-work-order",
        action_type="repair.dispatch",
        idempotency_key="idempotency-deterministic-work-order",
    )

    assert first == second
    assert uuid.UUID(str(first)).version == 5


class _RepairDispatchProbeTool(BaseTool):
    name: ClassVar[str] = "repair.dispatch"
    capability: ClassVar[ToolCapability] = ToolCapability.ACTION
    required_capabilities: ClassVar[frozenset[str]] = frozenset(
        {"tool.repair.dispatch"}
    )

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
    ) -> ToolInvocationResult:
        del request, context
        return ToolInvocationResult(
            output={"status": "success"},
            status="success",
            idempotency_key="repair-dispatch-probe",
        )


async def _invoke_repair_dispatch(
    *,
    tenant_id: str,
    tenant_repository: InMemoryTenantConfigurationRepository,
    seed: str,
) -> ToolInvocationEnvelope:
    registry = ToolRegistry()
    registry.register(_RepairDispatchProbeTool())
    invoker = ToolInvoker(
        tool_registry=registry,
        governance_runtime=build_action_tool_governance_runtime(
            persistence=InMemoryGovernanceRepository(),
            tenant_configuration_repository=tenant_repository,
        ),
    )
    return await invoker.invoke(
        ToolInvocationRequest(
            tool_name="repair.dispatch",
            payload={"order_id": "order-1", "product_sku": "A123"},
            metadata={
                "session_id": f"session-{seed}",
                "tool_name": "repair.dispatch",
                "action_type": "repair.dispatch",
                "target_resource": "repair:order-1:A123",
            },
        ),
        AgentExecutionContext(
            identity=AgentIdentity(
                agent_id="work-order-test-agent",
                runtime_instance_id=uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"work-order-runtime:{seed}",
                ),
            ),
            execution=ExecutionIdentity(
                execution_id=uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"work-order-execution:{seed}",
                ),
                request_id=f"req-work-order-{seed}",
            ),
            capabilities=CapabilitySet(
                (
                    AgentCapability(
                        name="tool.repair.dispatch",
                        scope=CapabilityScope.INVOKE,
                    ),
                )
            ),
            constraints=ExecutionConstraints(),
            causality=CausalityMetadata(),
            tenant_id=tenant_id,
            metadata={"session_id": f"session-{seed}"},
        ),
        invocation_ordinal=1,
    )


async def _seed_tenants(session: AsyncSession, *tenant_ids: str) -> None:
    for tenant_id in tenant_ids:
        await set_pg_rls_tenant(session, tenant_id)
        await session.merge(TenantRow(tenant_id=tenant_id))
    await session.flush()
    if tenant_ids:
        await set_pg_rls_tenant(session, tenant_ids[0])


def _record(
    tenant_id: str,
    *,
    seed: str,
    connector_version: int = 1,
) -> WorkOrderRecord:
    action_type = "repair.dispatch"
    idempotency_key = f"work-order:{seed}"
    return WorkOrderRecord(
        work_order_id=derive_work_order_id(
            tenant_id=tenant_id,
            action_type=action_type,
            idempotency_key=idempotency_key,
        ),
        tenant_id=tenant_id,
        action_type=action_type,
        tool_name="repair.dispatch",
        connector_type="generic_rest_work_order",
        connector_config_version=connector_version,
        connector_config_content_sha256=_CONTENT_SHA,
        connector_config_source_approval_id=_SOURCE_APPROVAL_ID,
        idempotency_key=idempotency_key,
        target_resource=f"repair:{seed}",
        metadata={"seed": seed},
    )


async def _save_action_policy(
    repository: InMemoryTenantConfigurationRepository,
    *,
    tenant_id: str,
    repair_dispatch_decision: str,
) -> None:
    parameters = _action_policy_parameters(
        repair_dispatch_decision=repair_dispatch_decision
    )
    content_sha256 = canonical_sha256(
        {
            "tenant_id": tenant_id,
            "policy_type": ACTION_TOOLS_POLICY_TYPE,
            "parameters": parameters,
            "status": TenantGovernancePolicyStatus.ACTIVE.value,
            "version": 1,
            "approved_by": "work-order-policy-admin",
            "effective_from": _NOW.isoformat(),
            "source_approval_id": "approval-work-order-action-policy",
        }
    )
    await repository.save_governance_policy(
        TenantGovernancePolicyRecord(
            policy_id=derive_governance_policy_version_id(
                tenant_id=tenant_id,
                policy_type=ACTION_TOOLS_POLICY_TYPE,
                version=1,
            ),
            tenant_id=tenant_id,
            policy_type=ACTION_TOOLS_POLICY_TYPE,
            parameters=parameters,
            status=TenantGovernancePolicyStatus.ACTIVE,
            version=1,
            approved_by="work-order-policy-admin",
            effective_from=_NOW,
            created_at=_NOW,
            source_approval_id="approval-work-order-action-policy",
            content_sha256=content_sha256,
            previous_version_sha256=None,
        ),
        expected_tenant_id=tenant_id,
    )


def _action_policy_parameters(
    *,
    repair_dispatch_decision: str,
) -> dict[str, object]:
    return {
        "phase": "2.3.x-a",
        "tools": {
            "warranty.claim": {
                "allow": {
                    "confidence_gte": 0.85,
                    "issue_category_in": ["charging_issue", "product_defect"],
                },
                "else": "require_approval",
            },
            "replacement.order": {"always": "require_approval"},
            "refund.request": {
                "allow": {"refund_amount_cents_lte": 5000},
                "else": "require_approval",
            },
            "warehouse.repair.report": {
                "allow": {"severity_in": ["low", "medium"]},
                "require_approval": {"severity_in": ["high", "critical"]},
            },
            "repair.dispatch": {"always": repair_dispatch_decision},
        },
    }
