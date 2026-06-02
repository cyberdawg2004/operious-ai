"""Phase 2.2 connector invocation idempotency ledger break-controls."""

from __future__ import annotations

import uuid
from typing import ClassVar

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import (
    AgentCapability,
    CapabilitySet,
    ExecutionConstraints,
)
from app.agents.context import AgentExecutionContext
from app.agents.enums import CapabilityScope
from app.agents.identity import AgentIdentity, ExecutionIdentity
from app.agents.results import ToolInvocationRequest, ToolInvocationResult
from app.agents.tools import BaseTool, ToolCapability, ToolInvoker, ToolRegistry
from app.agents.tools.action_governance import build_action_tool_governance_runtime
from app.agents.tools.connector_invocations import (
    CONNECTOR_INVOCATION_PENDING,
    CONNECTOR_INVOCATION_SUCCEEDED,
    ConnectorInvocationCompletionError,
    ConnectorInvocationRecord,
    ConnectorInvocationStatus,
    PostgresConnectorInvocationRepository,
)
from app.agents.tools.grants import AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY
from app.agents.value_objects import CausalityMetadata
from app.governance.persistence import PostgresGovernanceRepository
from app.tenant.db.models import TenantRow
from tests.conftest import requires_postgres, set_pg_rls_tenant

pytestmark = [pytest.mark.asyncio, requires_postgres]

_TENANT_ID = "tenant-connector-ledger"
_OTHER_TENANT_ID = "tenant-connector-ledger-other"
_TOOL_NAME = "refund.request"
_TARGET_RESOURCE = "order:order-22:sku:A1771"
_REQUEST_HASH = "a" * 64


@pytest.fixture
def pg_tenant_id() -> str:
    return _TENANT_ID


class _CountingRefundProvider(BaseTool):
    name: ClassVar[str] = _TOOL_NAME
    capability: ClassVar[ToolCapability] = ToolCapability.ACTION
    required_capabilities: ClassVar[frozenset[str]] = frozenset(
        {"tool.refund.request"}
    )

    def __init__(self, calls: list[dict[str, str]]) -> None:
        self._calls = calls

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
    ) -> ToolInvocationResult:
        del context
        provider_key = request.metadata.get(AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY)
        if not isinstance(provider_key, str) or not provider_key:
            raise RuntimeError("provider idempotency key missing")
        provider_id = f"refund-provider-{len(self._calls) + 1}"
        self._calls.append(
            {
                "provider_id": provider_id,
                "provider_key": provider_key,
            }
        )
        return ToolInvocationResult(
            output={
                "status": "success",
                "provider_id": provider_id,
                "provider_status": "succeeded",
            },
            status="success",
            idempotency_key=provider_key,
        )


class _CrashOnFirstCompleteLedger(PostgresConnectorInvocationRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.crashed = False

    async def complete_invocation(
        self,
        *,
        tenant_id: str,
        provider_idempotency_key: str,
        status: ConnectorInvocationStatus,
        provider_id: str | None,
        provider_status: str | None,
        provider_error: str | None,
    ) -> ConnectorInvocationRecord:
        if not self.crashed:
            self.crashed = True
            raise ConnectorInvocationCompletionError(
                "simulated terminal ledger write loss"
            )
        return await super().complete_invocation(
            tenant_id=tenant_id,
            provider_idempotency_key=provider_idempotency_key,
            status=status,
            provider_id=provider_id,
            provider_status=provider_status,
            provider_error=provider_error,
        )


async def test_pending_retry_does_not_invoke_provider_again(
    pg_session: AsyncSession,
) -> None:
    await _seed_tenants(pg_session, _TENANT_ID)
    calls: list[dict[str, str]] = []
    ledger = _CrashOnFirstCompleteLedger(pg_session)
    invoker = _invoker(pg_session, calls=calls, ledger=ledger)

    first = await invoker.invoke(
        _request(),
        _context(),
        invocation_ordinal=1,
    )

    assert first.is_ok is False
    assert (
        first.trace.metadata["reason"]
        == "connector_invocation_terminal_update_failed"
    )
    assert len(calls) == 1
    provider_key = calls[0]["provider_key"]
    pending = await PostgresConnectorInvocationRepository(pg_session).get_invocation(
        tenant_id=_TENANT_ID,
        provider_idempotency_key=provider_key,
    )
    assert pending is not None
    assert pending.status == CONNECTOR_INVOCATION_PENDING

    second = await invoker.invoke(
        _request(),
        _context(),
        invocation_ordinal=1,
    )

    assert second.is_ok is False
    assert (
        second.trace.metadata["reason"]
        == "connector_invocation_reconciliation_required"
    )
    assert len(calls) == 1


async def test_auto_allow_path_writes_connector_ledger(
    pg_session: AsyncSession,
) -> None:
    await _seed_tenants(pg_session, _TENANT_ID)
    calls: list[dict[str, str]] = []
    invoker = _invoker(
        pg_session,
        calls=calls,
        ledger=PostgresConnectorInvocationRepository(pg_session),
    )

    envelope = await invoker.invoke(
        _request(),
        _context(),
        invocation_ordinal=1,
    )

    assert envelope.is_ok
    assert envelope.provider_idempotency_key == calls[0]["provider_key"]
    record = await PostgresConnectorInvocationRepository(pg_session).get_invocation(
        tenant_id=_TENANT_ID,
        provider_idempotency_key=calls[0]["provider_key"],
    )
    assert record is not None
    assert record.status == CONNECTOR_INVOCATION_SUCCEEDED
    assert record.governance_decision_id is not None
    assert record.provider_id == calls[0]["provider_id"]


async def test_terminal_replay_returns_recorded_result_without_invoking(
    pg_session: AsyncSession,
) -> None:
    await _seed_tenants(pg_session, _TENANT_ID)
    calls: list[dict[str, str]] = []
    invoker = _invoker(
        pg_session,
        calls=calls,
        ledger=PostgresConnectorInvocationRepository(pg_session),
    )

    first = await invoker.invoke(
        _request(),
        _context(),
        invocation_ordinal=1,
    )
    second = await invoker.invoke(
        _request(),
        _context(),
        invocation_ordinal=1,
    )

    assert first.is_ok
    assert second.is_ok
    assert len(calls) == 1
    assert second.result is not None
    assert second.result.output["replayed"] is True
    assert second.result.output["provider_id"] == calls[0]["provider_id"]
    assert (
        second.trace.metadata["reason"]
        == "connector_invocation_terminal_replay"
    )


async def test_provider_key_unique_constraint_is_db_backstop(
    pg_session: AsyncSession,
) -> None:
    await _seed_tenants(pg_session, _TENANT_ID)
    await _insert_connector_invocation(
        pg_session,
        tenant_id=_TENANT_ID,
        provider_key="duplicate-provider-key",
    )

    with pytest.raises(IntegrityError):
        async with pg_session.begin_nested():
            await _insert_connector_invocation(
                pg_session,
                tenant_id=_TENANT_ID,
                provider_key="duplicate-provider-key",
            )


async def test_connector_ledger_forces_tenant_rls(
    pg_session: AsyncSession,
) -> None:
    await _seed_tenants(pg_session, _TENANT_ID, _OTHER_TENANT_ID)
    await PostgresConnectorInvocationRepository(pg_session).reserve_invocation(
        tenant_id=_TENANT_ID,
        provider_idempotency_key="tenant-a-provider-key",
        connector_type=_TOOL_NAME,
        action_type="refund_request",
        target_resource=_TARGET_RESOURCE,
        request_hash=_REQUEST_HASH,
        governance_decision_id=None,
    )

    try:
        await pg_session.execute(text("SET LOCAL ROLE operious_app_test"))
        await set_pg_rls_tenant(pg_session, _OTHER_TENANT_ID)
        visible = (
            await pg_session.execute(
                text(
                    """
                    SELECT provider_idempotency_key
                    FROM public.connector_invocations
                    WHERE tenant_id = :tenant_id
                    """
                ),
                {"tenant_id": _TENANT_ID},
            )
        ).all()
        assert visible == []

        with pytest.raises(SQLAlchemyError):
            async with pg_session.begin_nested():
                await _insert_connector_invocation(
                    pg_session,
                    tenant_id=_TENANT_ID,
                    provider_key="cross-tenant-provider-key",
                )
    finally:
        await pg_session.execute(text("RESET ROLE"))


def _invoker(
    session: AsyncSession,
    *,
    calls: list[dict[str, str]],
    ledger: PostgresConnectorInvocationRepository,
) -> ToolInvoker:
    registry = ToolRegistry()
    registry.register(_CountingRefundProvider(calls))
    return ToolInvoker(
        tool_registry=registry,
        governance_runtime=build_action_tool_governance_runtime(
            persistence=PostgresGovernanceRepository(session),
            redis_client=None,
        ),
        connector_invocation_repository=ledger,
    )


def _context() -> AgentExecutionContext:
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="connector-ledger-agent",
            runtime_instance_id=uuid.uuid5(
                uuid.NAMESPACE_URL, "connector-ledger-runtime"
            ),
        ),
        execution=ExecutionIdentity(
            execution_id=uuid.uuid5(
                uuid.NAMESPACE_URL, "connector-ledger-execution"
            ),
            request_id="req-connector-ledger",
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
        metadata={"session_id": "session-connector-ledger"},
    )


def _request() -> ToolInvocationRequest:
    return ToolInvocationRequest(
        tool_name=_TOOL_NAME,
        payload={
            "order_id": "order-22",
            "product_sku": "A1771",
            "refund_amount_cents": 2500,
            "refund_reason": "confirmed product defect",
        },
        metadata={
            "session_id": "session-connector-ledger",
            "tool_name": _TOOL_NAME,
            "action_type": "refund_request",
            "target_resource": _TARGET_RESOURCE,
            "target_resource_id": _TARGET_RESOURCE,
            "refund_amount_cents": 2500,
        },
    )


async def _seed_tenants(
    session: AsyncSession,
    *tenant_ids: str,
) -> None:
    for tenant_id in tenant_ids:
        await set_pg_rls_tenant(session, tenant_id)
        await session.merge(TenantRow(tenant_id=tenant_id))
    await session.flush()
    if tenant_ids:
        await set_pg_rls_tenant(session, tenant_ids[0])


async def _insert_connector_invocation(
    session: AsyncSession,
    *,
    tenant_id: str,
    provider_key: str,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO public.connector_invocations (
                tenant_id,
                provider_idempotency_key,
                connector_type,
                action_type,
                target_resource,
                request_hash,
                status,
                provider_id,
                provider_status,
                provider_error,
                attempt,
                governance_decision_id,
                completed_at
            )
            VALUES (
                :tenant_id,
                :provider_key,
                :connector_type,
                :action_type,
                :target_resource,
                :request_hash,
                'pending',
                NULL,
                NULL,
                NULL,
                1,
                NULL,
                NULL
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "provider_key": provider_key,
            "connector_type": _TOOL_NAME,
            "action_type": "refund_request",
            "target_resource": _TARGET_RESOURCE,
            "request_hash": _REQUEST_HASH,
        },
    )
