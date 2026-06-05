"""Phase 2.3.x-b repair.dispatch outbound action break-controls."""

from __future__ import annotations

import asyncio
import json
import os
import ssl
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from socket import socket as Socket
from typing import Any, cast
from urllib.parse import urlsplit

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import (
    AgentCapability,
    CapabilitySet,
    ExecutionConstraints,
)
from app.agents.context import AgentExecutionContext
from app.agents.enums import CapabilityScope
from app.agents.identity import AgentIdentity, ExecutionIdentity
from app.agents.results import ToolInvocationRequest
from app.agents.tools import ToolInvoker
from app.agents.tools.action_governance import (
    ACTION_TOOLS_POLICY_TYPE,
    build_action_tool_governance_runtime,
)
from app.agents.tools.actions import build_tenant_action_tool_registry
from app.agents.tools.connector_invocations import (
    PostgresConnectorInvocationRepository,
)
from app.agents.tools.connectors import (
    ConnectorConfigRecord,
    PostgresConnectorConfigRepository,
)
from app.agents.value_objects import CausalityMetadata
from app.core.ssrf import ValidatedPublicHTTPSURL
from app.governance.persistence import PostgresGovernanceRepository
from app.tenant.chronology import canonical_sha256
from app.tenant.enums import TenantChannelType, TenantGovernancePolicyStatus
from app.tenant.identity import derive_governance_policy_version_id
from app.tenant.persistence import (
    PostgresTenantConfigurationRepository,
    TenantGovernancePolicyRecord,
)
from app.work_orders.enums import WorkOrderState
from app.work_orders.exceptions import WorkOrderStateTransitionError
from app.work_orders.persistence import PostgresWorkOrderRepository
from app.work_orders.state_machine import assert_transition
from tests.conftest import requires_postgres, set_pg_rls_tenant

pytestmark = [pytest.mark.asyncio, requires_postgres]

_TOOL_NAME = "repair.dispatch"
_SECRET = "super-secret-repair-token"
_CONFIG_VERSION = 3
_CONFIG_SHA = "b" * 64
_SOURCE_APPROVAL_ID = "approval-repair-dispatch-config"
_POLICY_APPROVED_AT = datetime(2026, 6, 5, tzinfo=timezone.utc)


class _CredentialRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, TenantChannelType]] = []

    async def load_channel_credentials(
        self,
        *,
        tenant_id: str,
        channel_type: TenantChannelType,
    ) -> dict[str, Any]:
        self.calls.append((tenant_id, channel_type))
        assert channel_type == TenantChannelType.ZENDESK
        return {"auth_header": f"Bearer {_SECRET}:{tenant_id}"}


@requires_postgres
async def test_2_3_x_b_1_repair_dispatch_is_governed_and_fail_closed(
    pg_session: AsyncSession,
    tmp_path: Path,
) -> None:
    allowed_tenant = "tenant-repair-dispatch-allowed"
    denied_tenant = "tenant-repair-dispatch-no-policy"
    hostname = "repair-governed.local"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, hostname)
    server = await _start_repair_server_or_skip(
        cert_path=cert_path,
        key_path=key_path,
        provider_id="provider-repair-governed",
    )
    client_context = ssl.create_default_context(cafile=cert_path)

    try:
        endpoint = f"https://{hostname}:{_server_port(server.server)}/repairs"
        await _seed_connector_config(
            pg_session,
            tenant_id=allowed_tenant,
            endpoint_template=endpoint,
            endpoint_host=hostname,
        )
        await _seed_action_policy(
            pg_session,
            tenant_id=allowed_tenant,
            repair_dispatch_decision="allow",
        )
        await _seed_connector_config(
            pg_session,
            tenant_id=denied_tenant,
            endpoint_template=endpoint,
            endpoint_host=hostname,
        )

        allowed = await _invoke_socket_or_skip(
            _invoke_repair_dispatch(
                pg_session,
                tenant_id=allowed_tenant,
                request=_request(seed="governed"),
                context=_context(tenant_id=allowed_tenant, seed="governed"),
                ssl_context=client_context,
            )
        )
        denied = await _invoke_socket_or_skip(
            _invoke_repair_dispatch(
                pg_session,
                tenant_id=denied_tenant,
                request=_request(seed="governed-denied"),
                context=_context(
                    tenant_id=denied_tenant,
                    seed="governed-denied",
                ),
                ssl_context=client_context,
            )
        )
    finally:
        await _close_server(server.server)

    assert allowed.is_ok
    assert allowed.result is not None
    assert allowed.result.output["work_order_state"] == (
        WorkOrderState.AWAITING_FULFILLMENT.value
    )
    assert denied.is_denied
    assert denied.trace.metadata["reason"] == "governance_not_allow"
    assert server.post_count == 1

    allowed_orders = await PostgresWorkOrderRepository(pg_session).list_work_orders(
        expected_tenant_id=allowed_tenant,
    )
    denied_orders = await PostgresWorkOrderRepository(pg_session).list_work_orders(
        expected_tenant_id=denied_tenant,
    )
    assert len(allowed_orders) == 1
    assert allowed_orders[0].state is WorkOrderState.AWAITING_FULFILLMENT
    assert denied_orders == ()


@requires_postgres
async def test_2_3_x_b_2_repair_dispatch_is_idempotent_no_double_post(
    pg_session: AsyncSession,
    tmp_path: Path,
) -> None:
    tenant_id = "tenant-repair-dispatch-idempotent"
    hostname = "repair-idempotent.local"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, hostname)
    server = await _start_repair_server_or_skip(
        cert_path=cert_path,
        key_path=key_path,
        provider_id="provider-repair-idempotent",
    )
    client_context = ssl.create_default_context(cafile=cert_path)
    request = _request(seed="idempotent")
    context = _context(tenant_id=tenant_id, seed="idempotent")

    try:
        await _seed_connector_config(
            pg_session,
            tenant_id=tenant_id,
            endpoint_template=(
                f"https://{hostname}:{_server_port(server.server)}/repairs"
            ),
            endpoint_host=hostname,
        )
        await _seed_action_policy(
            pg_session,
            tenant_id=tenant_id,
            repair_dispatch_decision="allow",
        )

        first = await _invoke_socket_or_skip(
            _invoke_repair_dispatch(
                pg_session,
                tenant_id=tenant_id,
                request=request,
                context=context,
                ssl_context=client_context,
            )
        )
        second = await _invoke_socket_or_skip(
            _invoke_repair_dispatch(
                pg_session,
                tenant_id=tenant_id,
                request=request,
                context=context,
                ssl_context=client_context,
            )
        )
    finally:
        await _close_server(server.server)

    assert first.is_ok
    assert server.post_count == 1
    assert server.effect_count == 1
    assert server.idempotency_headers == [first.provider_idempotency_key]
    assert second.is_ok
    assert first.provider_idempotency_key == second.provider_idempotency_key
    assert second.result is not None
    assert second.result.output["replayed"] is True
    assert (
        second.trace.metadata["reason"]
        == "connector_invocation_terminal_replay"
    )
    orders = await PostgresWorkOrderRepository(pg_session).list_work_orders(
        expected_tenant_id=tenant_id,
    )
    assert len(orders) == 1
    assert uuid.UUID(str(orders[0].work_order_id)).version == 5
    assert orders[0].idempotency_key == first.provider_idempotency_key


@requires_postgres
async def test_2_3_x_b_3_repair_dispatch_binds_reconstruction_fields(
    pg_session: AsyncSession,
    tmp_path: Path,
) -> None:
    tenant_id = "tenant-repair-dispatch-reconstruction"
    hostname = "repair-reconstruction.local"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, hostname)
    server = await _start_repair_server_or_skip(
        cert_path=cert_path,
        key_path=key_path,
        provider_id="provider-repair-reconstruction",
    )
    client_context = ssl.create_default_context(cafile=cert_path)

    try:
        await _seed_connector_config(
            pg_session,
            tenant_id=tenant_id,
            endpoint_template=(
                f"https://{hostname}:{_server_port(server.server)}/repairs"
            ),
            endpoint_host=hostname,
            version=_CONFIG_VERSION,
            content_sha256=_CONFIG_SHA,
            source_approval_id=_SOURCE_APPROVAL_ID,
        )
        await _seed_action_policy(
            pg_session,
            tenant_id=tenant_id,
            repair_dispatch_decision="allow",
        )
        envelope = await _invoke_socket_or_skip(
            _invoke_repair_dispatch(
                pg_session,
                tenant_id=tenant_id,
                request=_request(seed="reconstruction"),
                context=_context(tenant_id=tenant_id, seed="reconstruction"),
                ssl_context=client_context,
            )
        )
    finally:
        await _close_server(server.server)

    assert envelope.is_ok
    orders = await PostgresWorkOrderRepository(pg_session).list_work_orders(
        expected_tenant_id=tenant_id,
    )
    assert len(orders) == 1
    record = orders[0]
    assert record.connector_config_version == _CONFIG_VERSION
    assert record.connector_config_content_sha256 == _CONFIG_SHA
    assert record.connector_config_source_approval_id == _SOURCE_APPROVAL_ID
    assert record.provider_work_order_id == "provider-repair-reconstruction"
    assert record.idempotency_key == envelope.provider_idempotency_key


@requires_postgres
async def test_2_3_x_b_4_repair_dispatch_ends_awaiting_not_fulfilled(
    pg_session: AsyncSession,
    tmp_path: Path,
) -> None:
    tenant_id = "tenant-repair-dispatch-state"
    hostname = "repair-state.local"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, hostname)
    server = await _start_repair_server_or_skip(
        cert_path=cert_path,
        key_path=key_path,
        provider_id="provider-repair-state",
    )
    client_context = ssl.create_default_context(cafile=cert_path)

    try:
        await _seed_connector_config(
            pg_session,
            tenant_id=tenant_id,
            endpoint_template=(
                f"https://{hostname}:{_server_port(server.server)}/repairs"
            ),
            endpoint_host=hostname,
        )
        await _seed_action_policy(
            pg_session,
            tenant_id=tenant_id,
            repair_dispatch_decision="allow",
        )
        envelope = await _invoke_socket_or_skip(
            _invoke_repair_dispatch(
                pg_session,
                tenant_id=tenant_id,
                request=_request(seed="state"),
                context=_context(tenant_id=tenant_id, seed="state"),
                ssl_context=client_context,
            )
        )
    finally:
        await _close_server(server.server)

    assert envelope.is_ok
    orders = await PostgresWorkOrderRepository(pg_session).list_work_orders(
        expected_tenant_id=tenant_id,
    )
    assert len(orders) == 1
    record = orders[0]
    assert record.state is WorkOrderState.AWAITING_FULFILLMENT
    assert [
        (item["from"], item["to"])
        for item in record.transition_history
    ] == [
        ("created", "dispatched"),
        ("dispatched", "awaiting_fulfillment"),
    ]
    assert record.state is not WorkOrderState.FULFILLED
    with pytest.raises(WorkOrderStateTransitionError):
        assert_transition(WorkOrderState.DISPATCHED, WorkOrderState.FULFILLED)


@requires_postgres
async def test_2_3_x_b_5_repair_dispatch_uses_tenant_connector_config(
    pg_session: AsyncSession,
    tmp_path: Path,
) -> None:
    tenant_a = "tenant-repair-dispatch-config-a"
    tenant_b = "tenant-repair-dispatch-config-b"
    no_config_tenant = "tenant-repair-dispatch-no-config"
    host_a = "repair-config-a.local"
    host_b = "repair-config-b.local"
    cert_a, key_a = _generate_self_signed_cert(tmp_path, host_a)
    cert_b, key_b = _generate_self_signed_cert(tmp_path, host_b)
    server_a = await _start_repair_server_or_skip(
        cert_path=cert_a,
        key_path=key_a,
        provider_id="provider-repair-config-a",
    )
    server_b = await _start_repair_server_or_skip(
        cert_path=cert_b,
        key_path=key_b,
        provider_id="provider-repair-config-b",
    )
    client_context = ssl.create_default_context(cafile=cert_a)
    client_context.load_verify_locations(cafile=cert_b)

    try:
        await _seed_connector_config(
            pg_session,
            tenant_id=tenant_a,
            endpoint_template=(
                f"https://{host_a}:{_server_port(server_a.server)}/tenant-a"
            ),
            endpoint_host=host_a,
        )
        await _seed_connector_config(
            pg_session,
            tenant_id=tenant_b,
            endpoint_template=(
                f"https://{host_b}:{_server_port(server_b.server)}/tenant-b"
            ),
            endpoint_host=host_b,
        )
        for tenant_id in (tenant_a, tenant_b, no_config_tenant):
            await _seed_action_policy(
                pg_session,
                tenant_id=tenant_id,
                repair_dispatch_decision="allow",
            )

        tenant_a_result = await _invoke_socket_or_skip(
            _invoke_repair_dispatch(
                pg_session,
                tenant_id=tenant_a,
                request=_request(seed="config-a"),
                context=_context(tenant_id=tenant_a, seed="config-a"),
                ssl_context=client_context,
            )
        )
        tenant_b_result = await _invoke_socket_or_skip(
            _invoke_repair_dispatch(
                pg_session,
                tenant_id=tenant_b,
                request=_request(seed="config-b"),
                context=_context(tenant_id=tenant_b, seed="config-b"),
                ssl_context=client_context,
            )
        )
        no_config_result = await _invoke_repair_dispatch(
            pg_session,
            tenant_id=no_config_tenant,
            request=_request(seed="no-config"),
            context=_context(tenant_id=no_config_tenant, seed="no-config"),
            ssl_context=client_context,
        )
    finally:
        await _close_server(server_a.server)
        await _close_server(server_b.server)

    assert tenant_a_result.is_ok
    assert tenant_b_result.is_ok
    assert no_config_result.is_denied
    assert no_config_result.trace.metadata["reason"] == "tool_not_found"
    assert server_a.request_paths == ["/tenant-a"]
    assert server_b.request_paths == ["/tenant-b"]
    assert server_a.post_count == 1
    assert server_b.post_count == 1
    assert await PostgresWorkOrderRepository(pg_session).list_work_orders(
        expected_tenant_id=no_config_tenant,
    ) == ()


@requires_postgres
async def test_repair_dispatch_provider_error_marks_work_order_failed(
    pg_session: AsyncSession,
    tmp_path: Path,
) -> None:
    tenant_id = "tenant-repair-dispatch-provider-error"
    hostname = "repair-provider-error.local"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, hostname)
    server = await _start_repair_server_or_skip(
        cert_path=cert_path,
        key_path=key_path,
        provider_id="provider-repair-error",
        response_status=500,
        provider_status="rejected",
        provider_error="repair queue unavailable",
    )
    client_context = ssl.create_default_context(cafile=cert_path)

    try:
        await _seed_connector_config(
            pg_session,
            tenant_id=tenant_id,
            endpoint_template=(
                f"https://{hostname}:{_server_port(server.server)}/repairs"
            ),
            endpoint_host=hostname,
        )
        await _seed_action_policy(
            pg_session,
            tenant_id=tenant_id,
            repair_dispatch_decision="allow",
        )
        envelope = await _invoke_socket_or_skip(
            _invoke_repair_dispatch(
                pg_session,
                tenant_id=tenant_id,
                request=_request(seed="provider-error"),
                context=_context(tenant_id=tenant_id, seed="provider-error"),
                ssl_context=client_context,
            )
        )
    finally:
        await _close_server(server.server)

    assert envelope.is_ok
    assert envelope.result is not None
    assert envelope.result.status == "error"
    assert server.post_count == 1
    orders = await PostgresWorkOrderRepository(pg_session).list_work_orders(
        expected_tenant_id=tenant_id,
    )
    assert len(orders) == 1
    assert orders[0].state is WorkOrderState.FAILED
    assert orders[0].provider_status == "rejected"
    assert orders[0].transition_history[-1]["to"] == "failed"
    assert (
        orders[0].transition_history[-1]["metadata"]["provider_error"]
        == "repair queue unavailable"
    )


async def _invoke_repair_dispatch(
    session: AsyncSession,
    *,
    tenant_id: str,
    request: ToolInvocationRequest,
    context: AgentExecutionContext,
    ssl_context: ssl.SSLContext,
) -> Any:
    await set_pg_rls_tenant(session, tenant_id)
    tenant_repository = PostgresTenantConfigurationRepository(session)
    registry = await build_tenant_action_tool_registry(
        tenant_id=tenant_id,
        config_repository=PostgresConnectorConfigRepository(session),
        credential_runtime=_CredentialRuntime(),
        work_order_repository=PostgresWorkOrderRepository(session),
        ssl_context=ssl_context,
        ssrf_validator=_local_validator,
    )
    invoker = ToolInvoker(
        tool_registry=registry,
        governance_runtime=build_action_tool_governance_runtime(
            persistence=PostgresGovernanceRepository(session),
            redis_client=None,
            tenant_configuration_repository=tenant_repository,
        ),
        connector_invocation_repository=PostgresConnectorInvocationRepository(
            session
        ),
    )
    return await invoker.invoke(request, context, invocation_ordinal=1)


def _request(*, seed: str) -> ToolInvocationRequest:
    order_id = f"order-{seed}"
    sku = f"sku-{seed}"
    return ToolInvocationRequest(
        tool_name=_TOOL_NAME,
        payload={
            "order_id": order_id,
            "product_sku": sku,
            "repair_reason": "confirmed product defect",
            "customer_description": f"repair request {seed}",
        },
        metadata={
            "tool_name": _TOOL_NAME,
            "action_type": _TOOL_NAME,
            "target_resource": f"repair:{order_id}:{sku}",
            "diagnostic_confidence": 0.94,
            "issue_category": "product_defect",
        },
    )


def _context(*, tenant_id: str, seed: str) -> AgentExecutionContext:
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="repair-dispatch-agent",
            runtime_instance_id=uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"repair-dispatch-runtime:{tenant_id}:{seed}",
            ),
        ),
        execution=ExecutionIdentity(
            execution_id=uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"repair-dispatch-execution:{tenant_id}:{seed}",
            ),
            request_id=f"req-repair-dispatch-{tenant_id}-{seed}",
        ),
        capabilities=CapabilitySet(
            (
                AgentCapability(
                    name="tool.repair.dispatch",
                    scope=CapabilityScope.INVOKE,
                ),
            )
        ),
        constraints=ExecutionConstraints(allowed_tools=(_TOOL_NAME,)),
        causality=CausalityMetadata(),
        tenant_id=tenant_id,
        metadata={},
    )


async def _seed_connector_config(
    session: AsyncSession,
    *,
    tenant_id: str,
    endpoint_template: str,
    endpoint_host: str,
    version: int = _CONFIG_VERSION,
    content_sha256: str = _CONFIG_SHA,
    source_approval_id: str = _SOURCE_APPROVAL_ID,
) -> None:
    await set_pg_rls_tenant(session, tenant_id)
    await PostgresConnectorConfigRepository(session).save_config(
        ConnectorConfigRecord(
            tenant_id=tenant_id,
            connector_type=TenantChannelType.ZENDESK.value,
            tool_name=_TOOL_NAME,
            http_method="POST",
            endpoint_template=endpoint_template,
            endpoint_host=endpoint_host,
            field_mappings={
                "order_id": "payload.order_id",
                "sku": "payload.product_sku",
                "reason": "payload.repair_reason",
                "customer_description": "payload.customer_description",
            },
            idempotency_header_name="X-Idempotency-Key",
            response_parse={
                "provider_work_order_id": "repair.id",
                "provider_status": "repair.status",
                "provider_error": "error.message",
            },
            success_status_codes=(200, 201, 202),
            status="active",
            version=version,
            configured_by="repair-dispatch-test",
            source_approval_id=source_approval_id,
            content_sha256=content_sha256,
        ),
        expected_tenant_id=tenant_id,
    )
    await session.flush()


async def _seed_action_policy(
    session: AsyncSession,
    *,
    tenant_id: str,
    repair_dispatch_decision: str,
) -> None:
    await set_pg_rls_tenant(session, tenant_id)
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
            "approved_by": "repair-dispatch-policy-admin",
            "effective_from": _POLICY_APPROVED_AT.isoformat(),
            "source_approval_id": "approval-repair-dispatch-policy",
        }
    )
    await PostgresTenantConfigurationRepository(session).save_governance_policy(
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
            approved_by="repair-dispatch-policy-admin",
            effective_from=_POLICY_APPROVED_AT,
            created_at=_POLICY_APPROVED_AT,
            source_approval_id="approval-repair-dispatch-policy",
            content_sha256=content_sha256,
            previous_version_sha256=None,
        ),
        expected_tenant_id=tenant_id,
    )
    await session.flush()


def _action_policy_parameters(
    *,
    repair_dispatch_decision: str,
) -> dict[str, object]:
    return {
        "phase": "2.3.x-b",
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
            _TOOL_NAME: {"always": repair_dispatch_decision},
        },
    }


def _local_validator(
    url: str,
    *,
    allowed_hosts: tuple[str, ...] = (),
) -> ValidatedPublicHTTPSURL:
    parsed = urlsplit(url)
    assert parsed.hostname in allowed_hosts
    return ValidatedPublicHTTPSURL(
        url=url,
        hostname=parsed.hostname or "",
        port=parsed.port or 443,
        pinned_ip="127.0.0.1",
    )


def _empty_optional_str_list() -> list[str | None]:
    return []


def _empty_str_list() -> list[str]:
    return []


def _empty_body_list() -> list[dict[str, Any]]:
    return []


def _empty_str_set() -> set[str]:
    return set()


@dataclass(slots=True)
class _RepairServer:
    server: asyncio.AbstractServer
    provider_id: str
    response_status: int = 201
    provider_status: str = "accepted"
    provider_error: str | None = None
    idempotency_headers: list[str | None] = field(
        default_factory=_empty_optional_str_list
    )
    authorization_headers: list[str | None] = field(
        default_factory=_empty_optional_str_list
    )
    request_paths: list[str] = field(default_factory=_empty_str_list)
    request_bodies: list[dict[str, Any]] = field(default_factory=_empty_body_list)
    _effect_keys: set[str] = field(default_factory=_empty_str_set)

    @property
    def post_count(self) -> int:
        return len(self.request_paths)

    @property
    def effect_count(self) -> int:
        return len(self._effect_keys)

    def record(
        self,
        *,
        path: str,
        headers: dict[str, str],
        body: bytes,
    ) -> None:
        key = headers.get("x-idempotency-key")
        self.idempotency_headers.append(key)
        self.authorization_headers.append(headers.get("authorization"))
        self.request_paths.append(path)
        decoded = cast(dict[str, Any], json.loads(body.decode("utf-8") or "{}"))
        assert isinstance(decoded, dict)
        self.request_bodies.append(decoded)
        if key:
            self._effect_keys.add(key)

    def response_body(self) -> bytes:
        if self.response_status in {200, 201, 202}:
            body = {
                "repair": {
                    "id": self.provider_id,
                    "status": self.provider_status,
                }
            }
        else:
            body = {
                "repair": {
                    "id": self.provider_id,
                    "status": self.provider_status,
                },
                "error": {"message": self.provider_error or "provider_error"},
            }
        return json.dumps(body).encode("utf-8")


async def _start_repair_server(
    *,
    cert_path: str,
    key_path: str,
    provider_id: str,
    response_status: int = 201,
    provider_status: str = "accepted",
    provider_error: str | None = None,
) -> _RepairServer:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert_path, keyfile=key_path)
    repair_server: _RepairServer | None = None

    async def _handle(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        assert repair_server is not None
        try:
            path, headers, body = await _read_request(reader)
            repair_server.record(path=path, headers=headers, body=body)
            response_body = repair_server.response_body()
            writer.write(
                f"HTTP/1.1 {response_status} OK\r\n".encode("ascii")
                + f"Content-Length: {len(response_body)}\r\n".encode("ascii")
                + b"Content-Type: application/json\r\n\r\n"
                + response_body
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(
        _handle,
        "127.0.0.1",
        0,
        ssl=context,
    )
    repair_server = _RepairServer(
        server=server,
        provider_id=provider_id,
        response_status=response_status,
        provider_status=provider_status,
        provider_error=provider_error,
    )
    return repair_server


async def _start_repair_server_or_skip(
    *,
    cert_path: str,
    key_path: str,
    provider_id: str,
    response_status: int = 201,
    provider_status: str = "accepted",
    provider_error: str | None = None,
) -> _RepairServer:
    try:
        return await _start_repair_server(
            cert_path=cert_path,
            key_path=key_path,
            provider_id=provider_id,
            response_status=response_status,
            provider_status=provider_status,
            provider_error=provider_error,
        )
    except OSError as exc:
        if not os.environ.get("CI"):
            pytest.skip(f"loopback bind unavailable in sandbox: {exc}")
        raise


async def _invoke_socket_or_skip(coro: Any) -> Any:
    try:
        return await asyncio.wait_for(coro, timeout=5.0)
    except (OSError, TimeoutError) as exc:
        if not os.environ.get("CI"):
            pytest.skip(f"loopback connector call unavailable in sandbox: {exc}")
        raise


async def _read_request(
    reader: asyncio.StreamReader,
) -> tuple[str, dict[str, str], bytes]:
    raw = await reader.readuntil(b"\r\n\r\n")
    lines = raw.decode("latin1").split("\r\n")
    request_line = lines[0]
    _, path, _ = request_line.split(" ", 2)
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            continue
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    raw_length = headers.get("content-length")
    body = b""
    if raw_length is not None:
        body = await reader.readexactly(int(raw_length))
    return path, headers, body


def _generate_self_signed_cert(
    tmp_path: Path,
    hostname: str,
) -> tuple[str, str]:
    cert_path = tmp_path / f"{hostname}.crt"
    key_path = tmp_path / f"{hostname}.key"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-days",
            "1",
            "-nodes",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-subj",
            f"/CN={hostname}",
            "-addext",
            f"subjectAltName=DNS:{hostname}",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return str(cert_path), str(key_path)


def _server_port(server: asyncio.AbstractServer) -> int:
    sockets = cast(tuple[Socket, ...] | None, getattr(server, "sockets", None))
    assert sockets is not None
    sockname = sockets[0].getsockname()
    assert isinstance(sockname, tuple)
    _, port = cast(tuple[str, int], sockname)
    return port


async def _close_server(server: asyncio.AbstractServer) -> None:
    server.close()
    await server.wait_closed()
