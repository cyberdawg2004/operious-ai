"""PR 4 break-control tests — warranty/replacement connectors.

Break-controls:
    #8  Idempotency / no-double-execute: same execution context + same
        payload → ledger short-circuits; second invoke makes ZERO extra
        HTTP calls.  Negative control: without the ledger the second
        invoke WOULD make a second HTTP call.
    #9  Fail-closed on unreachable / provider failure: provider errors return
        ToolInvocationResult(status="error"), and the ledger records failure.
    #10 Fail-closed when unconfigured: no active ConnectorConfigRecord
        → FailClosedActionTool registered, allow_stub_actions=False in
        prod path.
    #11 SSRF still applies: call-time URL blocked for private IPs.
    #12 Governance gates: no ALLOW decision → connector never invoked.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
import os
import ssl
from socket import socket as Socket
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, cast
from urllib.parse import urlsplit

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import VerifiedIdentity
from app.auth.providers import StaticTokenProvider
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
from app.agents.tools.action_governance import (
    ACTION_TOOLS_POLICY_TYPE,
    build_action_tool_governance_runtime,
)
from app.agents.tools.actions import (
    build_tenant_action_tool_registry,
)
from app.agents.tools.approvals import PostgresActionApprovalRepository
from app.agents.tools.connector_invocations import (
    CONNECTOR_INVOCATION_FAILED,
    CONNECTOR_INVOCATION_SUCCEEDED,
    ConnectorInvocationRecord,
    ConnectorInvocationReservation,
    ConnectorInvocationReservationStatus,
    ConnectorInvocationStatus,
    PostgresConnectorInvocationRepository,
)
from app.agents.tools.connectors import (
    ConnectorConfigRecord,
    GenericRestWarrantyClaimConnector,
    InMemoryConnectorConfigRepository,
    PostgresConnectorConfigRepository,
    ReplacementOrderConnector,
)
from app.agents.tools.grants import AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY
from app.agents.tools.orchestration import ActionOrchestrationRuntime
from app.agents.value_objects import CausalityMetadata
from app.core.config import get_settings
from app.dependencies.database import get_db_session
from app.dependencies.services import get_tenant_configuration_service
from app.governance.persistence import PostgresGovernanceRepository
from app.core.ssrf import (
    SSRFValidationError,
    ValidatedPublicHTTPSURL,
    validate_public_https_url,
)
from app.governance.persistence.memory import InMemoryGovernanceRepository
from app.main import create_app
from app.resolution.enums import (
    ResolutionAutonomyDecision,
    ResolutionGovernanceVerdict,
    ResolutionProposalStatus,
    ResolutionSupervisorVerdict,
)
from app.resolution.identity import ResolutionProposalId
from app.resolution.persistence.records import ResolutionProposalRecord
from app.runtime.timeline_runtime import TimelineRuntime
from app.session.enums import SessionLifecyclePhase, SessionScope
from app.session.identity import SessionId, SessionLineageId
from app.session.persistence import PostgresSessionPersistence, SessionRecord
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.chronology import canonical_sha256
from app.tenant.enums import (
    TenantChannelStatus,
    TenantChannelType,
    TenantGovernancePolicyStatus,
)
from app.tenant.identity import derive_governance_policy_version_id
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    PostgresTenantConfigurationRepository,
    TenantGovernancePolicyRecord,
)
from app.tenant.runtime import TenantConfigurationRuntime
from app.services.tenant_configuration_service import TenantConfigurationService
from tests.conftest import requires_postgres, set_pg_rls_tenant

_TENANT_ID = "tenant-warranty-pr4"
_WARRANTY_TOOL = "warranty.claim"
_REPLACEMENT_TOOL = "replacement.order"
_PROVIDER_KEY = "warranty-provider-key"
_POLICY_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)
_MASTER_KEY = "pr4-warranty-replacement-master-key-32b"


def _empty_string_list() -> list[str]:
    return []


def _empty_string_set() -> set[str]:
    return set()


# ─── In-memory connector invocation ledger ───────────────────────────────────


class InMemoryConnectorInvocationRepository:
    """Pure-in-memory idempotency ledger for unit tests."""

    def __init__(self) -> None:
        self._records: dict[str, ConnectorInvocationRecord] = {}

    async def reserve_invocation(
        self,
        *,
        tenant_id: str,
        provider_idempotency_key: str,
        connector_type: str,
        action_type: str,
        target_resource: str,
        request_hash: str,
        governance_decision_id: uuid.UUID | None,
    ) -> ConnectorInvocationReservation:
        existing = self._records.get(provider_idempotency_key)
        if existing is not None:
            status: ConnectorInvocationReservationStatus = (
                "terminal" if existing.status in {CONNECTOR_INVOCATION_SUCCEEDED, CONNECTOR_INVOCATION_FAILED}
                else "pending"
            )
            return ConnectorInvocationReservation(status=status, record=existing)
        record = ConnectorInvocationRecord(
            tenant_id=tenant_id,
            provider_idempotency_key=provider_idempotency_key,
            connector_type=connector_type,
            action_type=action_type,
            target_resource=target_resource,
            request_hash=request_hash,
            status="pending",
            provider_id=None,
            provider_status=None,
            provider_error=None,
            attempt=1,
            governance_decision_id=(
                str(governance_decision_id) if governance_decision_id is not None else None
            ),
            created_at=datetime.now(timezone.utc),
            completed_at=None,
        )
        self._records[provider_idempotency_key] = record
        return ConnectorInvocationReservation(status="new", record=record)

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
        existing = self._records[provider_idempotency_key]
        updated = ConnectorInvocationRecord(
            tenant_id=existing.tenant_id,
            provider_idempotency_key=existing.provider_idempotency_key,
            connector_type=existing.connector_type,
            action_type=existing.action_type,
            target_resource=existing.target_resource,
            request_hash=existing.request_hash,
            status=status,
            provider_id=provider_id,
            provider_status=provider_status,
            provider_error=provider_error,
            attempt=existing.attempt,
            governance_decision_id=existing.governance_decision_id,
            created_at=existing.created_at,
            completed_at=datetime.now(timezone.utc),
        )
        self._records[provider_idempotency_key] = updated
        return updated

    async def get_invocation(
        self,
        *,
        tenant_id: str,
        provider_idempotency_key: str,
    ) -> ConnectorInvocationRecord | None:
        return self._records.get(provider_idempotency_key)


# ─── Counting tool stub (for idempotency tests without TLS server) ────────────


class _CountingWarrantyTool(BaseTool):
    """Records how many times it is invoked; returns success."""

    name: ClassVar[str] = _WARRANTY_TOOL
    capability: ClassVar[ToolCapability] = ToolCapability.ACTION
    required_capabilities: ClassVar[frozenset[str]] = frozenset({"tool.warranty.claim"})

    def __init__(self) -> None:
        self.call_count = 0

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
    ) -> ToolInvocationResult:
        self.call_count += 1
        provider_key = request.metadata.get(AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY, "")
        return ToolInvocationResult(
            output={
                "status": "success",
                "provider_id": f"warranty-{self.call_count}",
                "provider_status": "approved",
            },
            status="success",
            idempotency_key=str(provider_key),
        )


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _warranty_request(*, target: str = "order:W-1:sku:X9") -> ToolInvocationRequest:
    return ToolInvocationRequest(
        tool_name=_WARRANTY_TOOL,
        payload={
            "order_id": "W-1",
            "product_sku": "X9",
            "customer_description": "battery swollen",
            "issue_category": "charging_issue",
        },
        metadata={
            "session_id": "session-warranty-pr4",
            "tool_name": _WARRANTY_TOOL,
            "action_type": "warranty_claim",
            "target_resource": target,
            "target_resource_id": target,
            "diagnostic_confidence": 0.92,
            "issue_category": "charging_issue",
            AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY: _PROVIDER_KEY,
        },
    )


def _replacement_request() -> ToolInvocationRequest:
    return ToolInvocationRequest(
        tool_name=_REPLACEMENT_TOOL,
        payload={
            "order_id": "R-1",
            "product_sku": "SKU-R1",
            "replacement_reason": "confirmed defect",
            "shipping_address_hash": "addr-hash-1",
        },
        metadata={
            "session_id": "session-warranty-pr4",
            "tool_name": _REPLACEMENT_TOOL,
            "action_type": "replacement_order",
            "target_resource": "order:R-1:sku:SKU-R1",
            AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY: "replacement-provider-key",
        },
    )


def _context(
    *,
    execution_id: uuid.UUID | None = None,
    request_id: str = "req-warranty-pr4",
    capabilities: CapabilitySet | None = None,
) -> AgentExecutionContext:
    if capabilities is None:
        capabilities = CapabilitySet(
            (
                AgentCapability(
                    name="tool.warranty.claim",
                    scope=CapabilityScope.INVOKE,
                ),
            )
        )
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="warranty-pr4-agent",
            runtime_instance_id=uuid.uuid5(uuid.NAMESPACE_URL, "warranty-pr4-runtime"),
        ),
        execution=ExecutionIdentity(
            execution_id=execution_id or uuid.uuid5(uuid.NAMESPACE_URL, "warranty-pr4-exec"),
            request_id=request_id,
        ),
        capabilities=capabilities,
        constraints=ExecutionConstraints(allowed_tools=(_WARRANTY_TOOL,)),
        causality=CausalityMetadata(),
        tenant_id=_TENANT_ID,
        metadata={"session_id": "session-warranty-pr4"},
    )


async def _seed_policy(repo: Any) -> None:
    parameters = {
        "phase": "2.4",
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
        },
    }
    content_sha256 = canonical_sha256(
        {
            "tenant_id": _TENANT_ID,
            "policy_type": ACTION_TOOLS_POLICY_TYPE,
            "parameters": parameters,
            "status": TenantGovernancePolicyStatus.ACTIVE.value,
            "version": 1,
            "approved_by": "test-policy-admin",
            "effective_from": _POLICY_AT.isoformat(),
            "source_approval_id": "approval-warranty-pr4",
        }
    )
    await repo.save_governance_policy(
        TenantGovernancePolicyRecord(
            policy_id=derive_governance_policy_version_id(
                tenant_id=_TENANT_ID,
                policy_type=ACTION_TOOLS_POLICY_TYPE,
                version=1,
            ),
            tenant_id=_TENANT_ID,
            policy_type=ACTION_TOOLS_POLICY_TYPE,
            parameters=parameters,
            status=TenantGovernancePolicyStatus.ACTIVE,
            version=1,
            approved_by="test-policy-admin",
            effective_from=_POLICY_AT,
            created_at=_POLICY_AT,
            source_approval_id="approval-warranty-pr4",
            content_sha256=content_sha256,
            previous_version_sha256=None,
        ),
        expected_tenant_id=_TENANT_ID,
    )


def _warranty_config(
    *,
    endpoint_template: str,
    endpoint_host: str,
) -> ConnectorConfigRecord:
    return ConnectorConfigRecord(
        tenant_id=_TENANT_ID,
        connector_type=TenantChannelType.ZENDESK.value,
        tool_name=_WARRANTY_TOOL,
        http_method="POST",
        endpoint_template=endpoint_template,
        endpoint_host=endpoint_host,
        field_mappings={
            "order_id": "payload.order_id",
            "sku": "payload.product_sku",
            "description": "payload.customer_description",
            "category": "payload.issue_category",
        },
        idempotency_header_name="X-Idempotency-Key",
        response_parse={
            "provider_id": "claim.id",
            "provider_status": "claim.status",
            "provider_error": "error.message",
        },
        success_status_codes=(200, 201, 202),
    )


async def _memory_warranty_config(
    *,
    endpoint_template: str,
    endpoint_host: str,
) -> InMemoryConnectorConfigRepository:
    repo = InMemoryConnectorConfigRepository()
    await repo.save_config(
        _warranty_config(
            endpoint_template=endpoint_template,
            endpoint_host=endpoint_host,
        ),
        expected_tenant_id=_TENANT_ID,
    )
    return repo


def _replacement_config(
    *,
    endpoint_template: str = "https://replacement.sandbox.example/orders",
    endpoint_host: str = "replacement.sandbox.example",
) -> ConnectorConfigRecord:
    return ConnectorConfigRecord(
        tenant_id=_TENANT_ID,
        connector_type=TenantChannelType.ZENDESK.value,
        tool_name=_REPLACEMENT_TOOL,
        http_method="POST",
        endpoint_template=endpoint_template,
        endpoint_host=endpoint_host,
        field_mappings={
            "order_id": "payload.order_id",
            "sku": "payload.product_sku",
            "reason": "payload.replacement_reason",
            "address_hash": "payload.shipping_address_hash",
        },
        idempotency_header_name="X-Idempotency-Key",
        response_parse={
            "provider_id": "replacement.id",
            "provider_status": "replacement.status",
            "provider_error": "error.message",
        },
        success_status_codes=(200, 201, 202),
    )


def _private_ip_validator(
    url: str,
    *,
    allowed_hosts: tuple[str, ...] = (),
) -> ValidatedPublicHTTPSURL:
    def _resolve(_host: str, _port: int) -> tuple[str, ...]:
        return ("10.0.0.1",)

    return validate_public_https_url(url, allowed_hosts=allowed_hosts, resolve=_resolve)


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


# ─── Local TLS server ────────────────────────────────────────────────────────


@dataclass(slots=True)
class _WarrantyServer:
    server: asyncio.AbstractServer
    request_count: int = 0
    idempotency_headers: list[str] = field(default_factory=_empty_string_list)
    _effect_keys: set[str] = field(default_factory=_empty_string_set)

    @property
    def effect_count(self) -> int:
        return len(self._effect_keys)

    def record(self, headers: dict[str, str]) -> None:
        self.request_count += 1
        key = headers.get("x-idempotency-key", "")
        self.idempotency_headers.append(key)
        if key:
            self._effect_keys.add(key)


async def _start_warranty_server(
    *,
    cert_path: str,
    key_path: str,
    status_code: int = 201,
    body: bytes = b'{"claim":{"id":"w-claim-1","status":"approved"}}',
) -> _WarrantyServer:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
    warranty_server: _WarrantyServer | None = None

    async def _handle(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        assert warranty_server is not None
        try:
            headers = await _read_headers(reader)
            await _drain_body(reader, headers)
            warranty_server.record(headers)
            status_line = f"HTTP/1.1 {status_code} OK\r\n".encode()
            writer.write(
                status_line
                + f"Content-Length: {len(body)}\r\n".encode()
                + b"Content-Type: application/json\r\n\r\n"
                + body
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(_handle, "127.0.0.1", 0, ssl=ctx)
    warranty_server = _WarrantyServer(server=server)
    return warranty_server


async def _start_server_or_skip(
    *,
    cert_path: str,
    key_path: str,
    status_code: int = 201,
    body: bytes = b'{"claim":{"id":"w-claim-1","status":"approved"}}',
) -> _WarrantyServer:
    try:
        return await _start_warranty_server(
            cert_path=cert_path,
            key_path=key_path,
            status_code=status_code,
            body=body,
        )
    except OSError as exc:
        if not os.environ.get("CI"):
            pytest.skip(f"loopback bind unavailable in sandbox: {exc}")
        raise


async def _invoke_or_skip(coro: Any) -> Any:
    try:
        return await asyncio.wait_for(coro, timeout=5.0)
    except (OSError, TimeoutError) as exc:
        if not os.environ.get("CI"):
            pytest.skip(f"loopback connector call unavailable in sandbox: {exc}")
        raise


async def _read_headers(reader: asyncio.StreamReader) -> dict[str, str]:
    raw = await reader.readuntil(b"\r\n\r\n")
    lines = raw.decode("latin1").split("\r\n")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            continue
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return headers


async def _drain_body(reader: asyncio.StreamReader, headers: dict[str, str]) -> None:
    raw_length = headers.get("content-length")
    if raw_length is None:
        return
    await reader.readexactly(int(raw_length))


def _generate_self_signed_cert(tmp_path: Path, hostname: str) -> tuple[str, str]:
    cert_path = tmp_path / f"{hostname}.crt"
    key_path = tmp_path / f"{hostname}.key"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256",
            "-days", "1", "-nodes",
            "-keyout", str(key_path),
            "-out", str(cert_path),
            "-subj", f"/CN={hostname}",
            "-addext", f"subjectAltName=DNS:{hostname}",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return str(cert_path), str(key_path)


def _server_port(server: asyncio.AbstractServer) -> int:
    server_obj = cast(Any, server)
    sockets = cast(list[Socket] | None, server_obj.sockets)
    assert sockets is not None
    return int(sockets[0].getsockname()[1])


async def _close_server(server: asyncio.AbstractServer) -> None:
    server.close()
    await server.wait_closed()


async def _seed_tenant(session: AsyncSession, tenant_id: str = _TENANT_ID) -> None:
    await session.execute(
        text(
            "INSERT INTO tenants (tenant_id, status) VALUES (:tenant_id, 'active') "
            "ON CONFLICT DO NOTHING"
        ),
        {"tenant_id": tenant_id},
    )


def _tenant_runtime(session: AsyncSession) -> TenantConfigurationRuntime:
    return TenantConfigurationRuntime(
        repository=PostgresTenantConfigurationRepository(session),
        credential_encryptor=TenantCredentialEncryptor(
            platform_master_key=_MASTER_KEY,
        ),
    )


async def _seed_postgres_warranty_channel(session: AsyncSession) -> None:
    await _tenant_runtime(session).configure_channel(
        tenant_id=_TENANT_ID,
        channel_type=TenantChannelType.ZENDESK,
        routing_address="support.warranty-pr4.example",
        credentials={"api_key": "sandbox-warranty-token"},
        webhook_secret="warranty-pr4-webhook-secret",
        status=TenantChannelStatus.ACTIVE,
    )


async def _seed_postgres_warranty_config(
    session: AsyncSession,
    *,
    endpoint_template: str,
    endpoint_host: str,
) -> None:
    await PostgresConnectorConfigRepository(session).save_config(
        _warranty_config(
            endpoint_template=endpoint_template,
            endpoint_host=endpoint_host,
        ),
        expected_tenant_id=_TENANT_ID,
    )


async def _seed_postgres_replacement_config(
    session: AsyncSession,
    *,
    endpoint_template: str,
    endpoint_host: str,
) -> None:
    await PostgresConnectorConfigRepository(session).save_config(
        _replacement_config(
            endpoint_template=endpoint_template,
            endpoint_host=endpoint_host,
        ),
        expected_tenant_id=_TENANT_ID,
    )


async def _postgres_invoker(
    session: AsyncSession,
    *,
    ssl_context: ssl.SSLContext | None = None,
    ssrf_validator: Any = _local_validator,
    with_ledger: bool = True,
) -> ToolInvoker:
    tenant_repository = PostgresTenantConfigurationRepository(session)
    return ToolInvoker(
        tool_registry=await build_tenant_action_tool_registry(
            tenant_id=_TENANT_ID,
            config_repository=PostgresConnectorConfigRepository(session),
            credential_runtime=_tenant_runtime(session),
            ssl_context=ssl_context,
            ssrf_validator=ssrf_validator,
            allow_stub_actions=False,
        ),
        governance_runtime=build_action_tool_governance_runtime(
            persistence=PostgresGovernanceRepository(session),
            redis_client=None,
            tenant_configuration_repository=tenant_repository,
        ),
        connector_invocation_repository=(
            PostgresConnectorInvocationRepository(session) if with_ledger else None
        ),
    )


def _orchestration_context(
    *,
    session_id: str,
    execution_id: str,
    request_id: str = "req-warranty-pr5",
) -> AgentExecutionContext:
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="warranty-pr5-agent",
            runtime_instance_id=uuid.uuid5(uuid.NAMESPACE_URL, "warranty-pr5-runtime"),
        ),
        execution=ExecutionIdentity(
            execution_id=uuid.UUID(execution_id),
            request_id=request_id,
        ),
        capabilities=CapabilitySet(
            (
                AgentCapability(
                    name="tool.warranty.claim",
                    scope=CapabilityScope.INVOKE,
                ),
            )
        ),
        constraints=ExecutionConstraints(allowed_tools=(_WARRANTY_TOOL,)),
        causality=CausalityMetadata(),
        tenant_id=_TENANT_ID,
        metadata={"session_id": session_id},
    )


def _session_record(*, session_id: str) -> SessionRecord:
    sid = SessionId(uuid.UUID(session_id))
    return SessionRecord(
        session_id=sid,
        scope=SessionScope.TENANT,
        external_handle="ticket-warranty-pr5",
        tenant_id=_TENANT_ID,
        principal_id="principal-agent",
        opened_at=_POLICY_AT,
        lifecycle_phase=SessionLifecyclePhase.ACTIVE,
        lifecycle_recorded_at=_POLICY_AT,
        lifecycle_reason=None,
        lineage_id=SessionLineageId(uuid.UUID(session_id)),
        root_session_id=sid,
        parent_session_id=None,
        ancestor_session_ids=(),
        lineage_depth=0,
        sequence_head=-1,
        revision=0,
    )


async def _seed_session(
    session: AsyncSession,
    *,
    session_id: str,
) -> None:
    await PostgresSessionPersistence(session).save_session(
        _session_record(session_id=session_id)
    )


def _proposal(
    *,
    seed: str,
    requires_execution: bool,
) -> ResolutionProposalRecord:
    session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{seed}:session"))
    execution_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{seed}:execution"))
    return ResolutionProposalRecord(
        proposal_id=ResolutionProposalId(
            uuid.uuid5(uuid.NAMESPACE_URL, f"{seed}:proposal")
        ),
        tenant_id=_TENANT_ID,
        session_id=session_id,
        execution_id=execution_id,
        dispatch_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{seed}:dispatch")),
        diagnostic_event_id=str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"{seed}:diagnostic")
        ),
        proposed_customer_reply="We will review the warranty issue.",
        resolution_category="charging_issue",
        confidence=0.92,
        supervisor_verdict=ResolutionSupervisorVerdict.PASS,
        governance_verdict=ResolutionGovernanceVerdict.ALLOW,
        autonomy_decision=ResolutionAutonomyDecision.AUTO_APPROVED,
        status=ResolutionProposalStatus.SEND_ELIGIBLE,
        governance_decision_id=uuid.uuid5(
            uuid.NAMESPACE_URL, f"{seed}:proposal-governance"
        ),
        recommended_actions=(
            {
                "type": "warranty_claim",
                "requires_execution": requires_execution,
                "tool_name": _WARRANTY_TOOL,
                "target_resource_id": "order:W-1:sku:X9",
                "payload": dict(_warranty_request().payload),
                "issue_category": "charging_issue",
            },
        ),
        evidence=(),
        created_at=_POLICY_AT,
        updated_at=_POLICY_AT,
    )


async def _orchestration_runtime(
    session: AsyncSession,
    *,
    ssl_context: ssl.SSLContext | None = None,
    ssrf_validator: Any = _local_validator,
) -> ActionOrchestrationRuntime:
    return ActionOrchestrationRuntime(
        tool_invoker=await _postgres_invoker(
            session,
            ssl_context=ssl_context,
            ssrf_validator=ssrf_validator,
        ),
        approval_repository=PostgresActionApprovalRepository(session),
        timeline_runtime=TimelineRuntime(
            persistence=PostgresSessionPersistence(session)
        ),
    )


async def _count_connector_invocations(session: AsyncSession) -> int:
    row = await session.execute(
        text(
            """
            SELECT count(*)
            FROM public.connector_invocations
            WHERE tenant_id = :tenant_id
            """
        ),
        {"tenant_id": _TENANT_ID},
    )
    return int(row.scalar_one())


def _router_headers(role: str = "admin") -> dict[str, str]:
    return {"Authorization": f"Bearer {_TENANT_ID}-{role}"}


@asynccontextmanager
async def _connector_test_client(
    pg_session: AsyncSession,
    *,
    ssl_context: ssl.SSLContext | None = None,
    ssrf_validator: Any | None = None,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    get_settings.cache_clear()
    provider = StaticTokenProvider(
        tokens={
            f"{_TENANT_ID}-admin": VerifiedIdentity(
                tenant_id=_TENANT_ID,
                principal_id="principal-admin",
                capabilities=frozenset({"tenant.connector.write"}),
            ),
            f"{_TENANT_ID}-empty": VerifiedIdentity(
                tenant_id=_TENANT_ID,
                principal_id="principal-empty",
                capabilities=frozenset(),
            ),
        }
    )
    app = create_app(auth_provider=cast(Any, provider))

    async def _override_db() -> AsyncIterator[AsyncSession]:
        yield pg_session

    def _override_service() -> TenantConfigurationService:
        return TenantConfigurationService(
            runtime=TenantConfigurationRuntime(
                repository=PostgresTenantConfigurationRepository(pg_session),
                credential_encryptor=TenantCredentialEncryptor(
                    platform_master_key=_MASTER_KEY,
                ),
            ),
            session=pg_session,
            redis_client=None,
            connector_test_ssl_context=ssl_context,
            connector_test_ssrf_validator=ssrf_validator,
        )

    app.dependency_overrides[get_db_session] = _override_db
    app.dependency_overrides[get_tenant_configuration_service] = (
        _override_service
    )

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            yield client
    finally:
        get_settings.cache_clear()


def _unused_loopback_port() -> int:
    sock = Socket()
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


# ─── Break-control #8: idempotency (no-double-execute) ───────────────────────


@pytest.mark.asyncio
async def test_idempotency_second_invoke_makes_zero_extra_calls() -> None:
    """Same execution context + same payload → second invoke replays from ledger.

    Both invokes share the same AgentExecutionContext (same execution_id +
    request_id + tool_name + payload hash) so the invoker derives the same
    governance.decision_seed → same seeded_decision_id → same
    provider_idempotency_key.  First invoke: governance evaluates → persists
    ALLOW → reserve (new) → tool called once → complete (succeeded).  Second
    invoke: get_persisted_decision returns the ALLOW → reserve (terminal) →
    replay without calling the tool.
    """
    policy_repo = InMemoryTenantConfigurationRepository()
    await _seed_policy(policy_repo)

    counting_tool = _CountingWarrantyTool()
    registry = ToolRegistry()
    registry.register(counting_tool)

    ledger = InMemoryConnectorInvocationRepository()
    invoker = ToolInvoker(
        tool_registry=registry,
        governance_runtime=build_action_tool_governance_runtime(
            persistence=InMemoryGovernanceRepository(),
            redis_client=None,
            tenant_configuration_repository=policy_repo,
        ),
        connector_invocation_repository=ledger,
    )

    ctx = _context()
    req = _warranty_request()

    first = await invoker.invoke(req, ctx, invocation_ordinal=1)
    second = await invoker.invoke(req, ctx, invocation_ordinal=1)

    assert first.is_ok, f"first invoke failed: {first.trace.metadata}"
    assert second.is_ok, f"second invoke failed: {second.trace.metadata}"
    assert counting_tool.call_count == 1, (
        f"connector was called {counting_tool.call_count} times; expected 1"
    )
    assert second.result is not None
    assert second.result.output["replayed"] is True
    assert second.trace.metadata["reason"] == "connector_invocation_terminal_replay"


@pytest.mark.asyncio
async def test_idempotency_negative_control_without_ledger_makes_second_call() -> None:
    """Without the ledger, second invoke DOES call the tool a second time.

    This negative control proves the ledger is what prevents the double-execute,
    not some other mechanism.
    """
    policy_repo = InMemoryTenantConfigurationRepository()
    await _seed_policy(policy_repo)

    counting_tool = _CountingWarrantyTool()
    registry = ToolRegistry()
    registry.register(counting_tool)

    invoker_no_ledger = ToolInvoker(
        tool_registry=registry,
        governance_runtime=build_action_tool_governance_runtime(
            persistence=InMemoryGovernanceRepository(),
            redis_client=None,
            tenant_configuration_repository=policy_repo,
        ),
        # No connector_invocation_repository → no idempotency gate
    )

    ctx = _context()
    req = _warranty_request()

    first = await invoker_no_ledger.invoke(req, ctx, invocation_ordinal=1)
    second = await invoker_no_ledger.invoke(req, ctx, invocation_ordinal=1)

    assert first.is_ok, f"first invoke failed: {first.trace.metadata}"
    assert second.is_ok, f"second invoke failed: {second.trace.metadata}"
    assert counting_tool.call_count == 2, (
        f"expected 2 calls without ledger, got {counting_tool.call_count}"
    )


@requires_postgres
async def test_postgres_idempotency_replays_warranty_without_second_http_call(
    pg_session: AsyncSession,
    tmp_path: Path,
) -> None:
    hostname = "warranty-pr4-postgres-idempotency.local"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, hostname)
    server = await _start_server_or_skip(
        cert_path=cert_path,
        key_path=key_path,
    )
    client_ctx = ssl.create_default_context(cafile=cert_path)
    client_ctx.check_hostname = True

    try:
        await set_pg_rls_tenant(pg_session, _TENANT_ID)
        await _seed_tenant(pg_session)
        await _seed_postgres_warranty_channel(pg_session)
        await _seed_postgres_warranty_config(
            pg_session,
            endpoint_template=(
                f"https://{hostname}:{_server_port(server.server)}/claims"
            ),
            endpoint_host=hostname,
        )
        await _seed_policy(PostgresTenantConfigurationRepository(pg_session))
        invoker = await _postgres_invoker(
            pg_session,
            ssl_context=client_ctx,
        )

        first = await _invoke_or_skip(
            invoker.invoke(_warranty_request(), _context(), invocation_ordinal=1)
        )
        second = await _invoke_or_skip(
            invoker.invoke(_warranty_request(), _context(), invocation_ordinal=1)
        )
    finally:
        await _close_server(server.server)

    assert first.is_ok, f"first invoke failed: {first.trace.metadata}"
    assert second.is_ok, f"second invoke failed: {second.trace.metadata}"
    assert server.request_count == 1
    assert second.result is not None
    assert second.result.output["replayed"] is True
    assert second.trace.metadata["reason"] == "connector_invocation_terminal_replay"


@requires_postgres
async def test_postgres_negative_control_without_ledger_makes_second_http_call(
    pg_session: AsyncSession,
    tmp_path: Path,
) -> None:
    hostname = "warranty-pr4-postgres-no-ledger.local"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, hostname)
    server = await _start_server_or_skip(
        cert_path=cert_path,
        key_path=key_path,
    )
    client_ctx = ssl.create_default_context(cafile=cert_path)
    client_ctx.check_hostname = True

    try:
        await set_pg_rls_tenant(pg_session, _TENANT_ID)
        await _seed_tenant(pg_session)
        await _seed_postgres_warranty_channel(pg_session)
        await _seed_postgres_warranty_config(
            pg_session,
            endpoint_template=(
                f"https://{hostname}:{_server_port(server.server)}/claims"
            ),
            endpoint_host=hostname,
        )
        await _seed_policy(PostgresTenantConfigurationRepository(pg_session))
        invoker = await _postgres_invoker(
            pg_session,
            ssl_context=client_ctx,
            with_ledger=False,
        )

        first = await _invoke_or_skip(
            invoker.invoke(_warranty_request(), _context(), invocation_ordinal=1)
        )
        second = await _invoke_or_skip(
            invoker.invoke(_warranty_request(), _context(), invocation_ordinal=1)
        )
    finally:
        await _close_server(server.server)

    assert first.is_ok, f"first invoke failed: {first.trace.metadata}"
    assert second.is_ok, f"second invoke failed: {second.trace.metadata}"
    assert server.request_count == 2


# ─── Break-control #9: fail-closed on non-2xx / unreachable ─────────────────


@pytest.mark.asyncio
async def test_non_success_status_code_returns_failure(tmp_path: Path) -> None:
    """HTTP 500 from provider → ToolInvocationResult(status="error")."""
    hostname = "warranty-pr4-error.local"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, hostname)
    server = await _start_server_or_skip(
        cert_path=cert_path,
        key_path=key_path,
        status_code=500,
        body=b'{"error":{"message":"provider system error"}}',
    )
    client_ctx = ssl.create_default_context(cafile=cert_path)
    client_ctx.check_hostname = True
    connector = GenericRestWarrantyClaimConnector(
        config_repository=await _memory_warranty_config(
            endpoint_template=f"https://{hostname}:{_server_port(server.server)}/claims",
            endpoint_host=hostname,
        ),
        credential_runtime=_CredentialRuntime(),
        ssl_context=client_ctx,
        ssrf_validator=_local_validator,
    )

    try:
        result = await _invoke_or_skip(connector.invoke(_warranty_request(), _context()))
    finally:
        await _close_server(server.server)

    assert result.status == "error"
    assert result.error_code == "provider_error"
    assert result.error_message is not None
    assert result.output["status"] == "error"


@pytest.mark.asyncio
async def test_invoker_records_failure_in_ledger_on_non_success(
    tmp_path: Path,
) -> None:
    """Non-success HTTP response → ledger records FAILED, not SUCCEEDED."""
    hostname = "warranty-pr4-fail-ledger.local"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, hostname)
    server = await _start_server_or_skip(
        cert_path=cert_path,
        key_path=key_path,
        status_code=422,
        body=b'{"error":{"message":"unprocessable warranty claim"}}',
    )
    client_ctx = ssl.create_default_context(cafile=cert_path)
    client_ctx.check_hostname = True

    policy_repo = InMemoryTenantConfigurationRepository()
    await _seed_policy(policy_repo)
    ledger = InMemoryConnectorInvocationRepository()

    config_repo = await _memory_warranty_config(
        endpoint_template=f"https://{hostname}:{_server_port(server.server)}/claims",
        endpoint_host=hostname,
    )
    registry = ToolRegistry()
    registry.register(
        GenericRestWarrantyClaimConnector(
            config_repository=config_repo,
            credential_runtime=_CredentialRuntime(),
            ssl_context=client_ctx,
            ssrf_validator=_local_validator,
        )
    )
    invoker = ToolInvoker(
        tool_registry=registry,
        governance_runtime=build_action_tool_governance_runtime(
            persistence=InMemoryGovernanceRepository(),
            redis_client=None,
            tenant_configuration_repository=policy_repo,
        ),
        connector_invocation_repository=ledger,
    )

    try:
        envelope = await _invoke_or_skip(
            invoker.invoke(_warranty_request(), _context(), invocation_ordinal=1)
        )
    finally:
        await _close_server(server.server)

    assert envelope.is_ok
    assert envelope.result is not None
    assert envelope.result.status == "error"
    provider_key = envelope.provider_idempotency_key
    assert provider_key is not None
    record = await ledger.get_invocation(
        tenant_id=_TENANT_ID,
        provider_idempotency_key=provider_key,
    )
    assert record is not None
    assert record.status == CONNECTOR_INVOCATION_FAILED


@requires_postgres
async def test_postgres_unreachable_connector_fails_closed_and_replays_failure(
    pg_session: AsyncSession,
) -> None:
    port = _unused_loopback_port()
    hostname = "warranty-pr4-unreachable.local"

    await set_pg_rls_tenant(pg_session, _TENANT_ID)
    await _seed_tenant(pg_session)
    await _seed_postgres_warranty_channel(pg_session)
    await _seed_postgres_warranty_config(
        pg_session,
        endpoint_template=f"https://{hostname}:{port}/claims",
        endpoint_host=hostname,
    )
    await _seed_policy(PostgresTenantConfigurationRepository(pg_session))
    invoker = await _postgres_invoker(pg_session)

    first = await invoker.invoke(_warranty_request(), _context(), invocation_ordinal=1)
    second = await invoker.invoke(_warranty_request(), _context(), invocation_ordinal=1)

    assert first.is_ok
    assert first.result is not None
    assert first.result.status == "error"
    assert first.result.error_code == "provider_transport_error"
    provider_key = first.provider_idempotency_key
    assert provider_key is not None
    record = await PostgresConnectorInvocationRepository(pg_session).get_invocation(
        tenant_id=_TENANT_ID,
        provider_idempotency_key=provider_key,
    )
    assert record is not None
    assert record.status == CONNECTOR_INVOCATION_FAILED
    assert second.is_ok is False
    assert second.trace.metadata["reason"] == "connector_invocation_terminal_replay"


# ─── Break-control #10: fail-closed when unconfigured ────────────────────────


@pytest.mark.asyncio
async def test_unconfigured_warranty_absent_from_registry_in_prod() -> None:
    """No active ConnectorConfigRecord → tool absent from registry (domain-agnostic design).

    The old contract was: unconfigured → FailClosedActionTool with hardcoded name.
    New contract: unconfigured → absent from registry entirely. No hardcoded tool names.
    """
    from app.agents.exceptions import ToolNotFoundError

    registry = await build_tenant_action_tool_registry(
        tenant_id=_TENANT_ID,
        config_repository=InMemoryConnectorConfigRepository(),
        credential_runtime=_CredentialRuntime(),
        allow_stub_actions=False,
    )
    assert registry.names() == (), "unconfigured tenant must have empty registry"
    try:
        registry.get(_WARRANTY_TOOL)
        pytest.fail(f"{_WARRANTY_TOOL!r} should not exist in unconfigured registry")
    except ToolNotFoundError:
        pass  # expected


@pytest.mark.asyncio
async def test_unconfigured_replacement_absent_from_registry_in_prod() -> None:
    """No active ConnectorConfigRecord → tool absent from registry."""
    from app.agents.exceptions import ToolNotFoundError

    registry = await build_tenant_action_tool_registry(
        tenant_id=_TENANT_ID,
        config_repository=InMemoryConnectorConfigRepository(),
        credential_runtime=_CredentialRuntime(),
        allow_stub_actions=False,
    )
    try:
        registry.get(_REPLACEMENT_TOOL)
        pytest.fail(f"{_REPLACEMENT_TOOL!r} should not exist in unconfigured registry")
    except ToolNotFoundError:
        pass  # expected


@pytest.mark.asyncio
async def test_unconfigured_warranty_absent_in_nonprod() -> None:
    """No active config + allow_stub_actions=True → still absent from registry.

    The domain-agnostic design has no hardcoded stub tools. allow_stub_actions
    has no effect — stubs were removed with the hardcoded tool registry.
    """
    from app.agents.exceptions import ToolNotFoundError

    registry = await build_tenant_action_tool_registry(
        tenant_id=_TENANT_ID,
        config_repository=InMemoryConnectorConfigRepository(),
        credential_runtime=_CredentialRuntime(),
        allow_stub_actions=True,
    )
    try:
        registry.get(_WARRANTY_TOOL)
        pytest.fail(f"{_WARRANTY_TOOL!r} should not exist in unconfigured registry")
    except ToolNotFoundError:
        pass  # expected


@pytest.mark.asyncio
async def test_configured_warranty_registers_generic_connector() -> None:
    """Active ConnectorConfigRecord → GenericConnectorTool registered under tool_name."""
    from app.agents.tools.connectors import GenericConnectorTool

    config_repo = await _memory_warranty_config(
        endpoint_template="https://warranty.sandbox.example/claims",
        endpoint_host="warranty.sandbox.example",
    )
    registry = await build_tenant_action_tool_registry(
        tenant_id=_TENANT_ID,
        config_repository=config_repo,
        credential_runtime=_CredentialRuntime(),
        allow_stub_actions=False,
    )

    tool = registry.get(_WARRANTY_TOOL)
    assert isinstance(tool, GenericConnectorTool), (
        f"expected GenericConnectorTool, got {type(tool).__name__}"
    )


@pytest.mark.asyncio
async def test_configured_replacement_registers_generic_connector() -> None:
    """Active ConnectorConfigRecord → GenericConnectorTool registered under tool_name."""
    from app.agents.tools.connectors import GenericConnectorTool

    repo = InMemoryConnectorConfigRepository()
    await repo.save_config(
        _replacement_config(),
        expected_tenant_id=_TENANT_ID,
    )
    registry = await build_tenant_action_tool_registry(
        tenant_id=_TENANT_ID,
        config_repository=repo,
        credential_runtime=_CredentialRuntime(),
        allow_stub_actions=False,
    )

    tool = registry.get(_REPLACEMENT_TOOL)
    assert isinstance(tool, GenericConnectorTool), (
        f"expected GenericConnectorTool, got {type(tool).__name__}"
    )


@requires_postgres
async def test_replacement_order_reaches_sandbox_and_succeeds(
    pg_session: AsyncSession,
    tmp_path: Path,
) -> None:
    hostname = "replacement-pr4-ok.local"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, hostname)
    server = await _start_server_or_skip(
        cert_path=cert_path,
        key_path=key_path,
        body=b'{"replacement":{"id":"replacement-1","status":"accepted"}}',
    )
    client_ctx = ssl.create_default_context(cafile=cert_path)
    client_ctx.check_hostname = True

    await set_pg_rls_tenant(pg_session, _TENANT_ID)
    await _seed_tenant(pg_session)
    await _seed_postgres_warranty_channel(pg_session)
    await _seed_postgres_replacement_config(
        pg_session,
        endpoint_template=(
            f"https://{hostname}:{_server_port(server.server)}/orders"
        ),
        endpoint_host=hostname,
    )
    connector = ReplacementOrderConnector(
        config_repository=PostgresConnectorConfigRepository(pg_session),
        credential_runtime=_tenant_runtime(pg_session),
        ssl_context=client_ctx,
        ssrf_validator=_local_validator,
    )

    try:
        result = await _invoke_or_skip(
            connector.invoke(_replacement_request(), _context())
        )
    finally:
        await _close_server(server.server)

    assert result.status == "success"
    assert result.output.get("provider_id") == "replacement-1"
    assert result.output.get("provider_status") == "accepted"
    assert server.request_count == 1


# ─── Break-control #11: SSRF still applies ───────────────────────────────────


@pytest.mark.asyncio
async def test_warranty_connector_blocks_private_ip_at_call_time() -> None:
    """SSRF guard rejects private IP resolution before any network call."""
    connector = GenericRestWarrantyClaimConnector(
        config_repository=await _memory_warranty_config(
            endpoint_template="https://warranty.internal/claims",
            endpoint_host="warranty.internal",
        ),
        credential_runtime=_CredentialRuntime(),
        ssrf_validator=_private_ip_validator,
    )

    with pytest.raises(SSRFValidationError):
        await connector.invoke(_warranty_request(), _context())


# ─── Break-control #12: governance gates the connector ───────────────────────


@pytest.mark.asyncio
async def test_governance_deny_blocks_warranty_connector() -> None:
    """Governance DENY → connector never invoked, credentials never loaded."""
    credentials = _CredentialRuntime()
    registry = ToolRegistry()
    registry.register(
        GenericRestWarrantyClaimConnector(
            config_repository=await _memory_warranty_config(
                endpoint_template="https://warranty.sandbox.example/claims",
                endpoint_host="warranty.sandbox.example",
            ),
            credential_runtime=credentials,
            ssrf_validator=_private_ip_validator,
        )
    )

    policy_repo = InMemoryTenantConfigurationRepository()
    await _seed_policy(policy_repo)

    envelope = await ToolInvoker(
        tool_registry=registry,
        governance_runtime=build_action_tool_governance_runtime(
            persistence=InMemoryGovernanceRepository(),
            redis_client=None,
            tenant_configuration_repository=policy_repo,
        ),
    ).invoke(
        ToolInvocationRequest(
            tool_name=_WARRANTY_TOOL,
            payload={
                "order_id": "W-bad",
                "product_sku": "Z1",
                "issue_description": "unknown",
                "issue_category": "unknown_category",
            },
            metadata={
                "session_id": "session-warranty-pr4",
                "tool_name": _WARRANTY_TOOL,
                "action_type": "warranty_claim",
                "target_resource": "order:W-bad:sku:Z1",
                "diagnostic_confidence": 0.5,  # below threshold
                "issue_category": "unknown_category",  # not in allowed set
            },
        ),
        _context(),
        invocation_ordinal=1,
    )

    assert envelope.is_denied, f"expected denied, got: {envelope.trace.metadata}"
    assert credentials.calls == 0, "credentials should not be loaded when governance denies"


# ─── Full happy-path via TLS sandbox ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_warranty_claim_reaches_sandbox_and_succeeds(tmp_path: Path) -> None:
    """Warranty claim reaches the local TLS sandbox and returns success."""
    hostname = "warranty-pr4-ok.local"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, hostname)
    server = await _start_server_or_skip(
        cert_path=cert_path,
        key_path=key_path,
    )
    client_ctx = ssl.create_default_context(cafile=cert_path)
    client_ctx.check_hostname = True
    connector = GenericRestWarrantyClaimConnector(
        config_repository=await _memory_warranty_config(
            endpoint_template=f"https://{hostname}:{_server_port(server.server)}/claims",
            endpoint_host=hostname,
        ),
        credential_runtime=_CredentialRuntime(),
        ssl_context=client_ctx,
        ssrf_validator=_local_validator,
    )

    try:
        result = await _invoke_or_skip(
            connector.invoke(_warranty_request(), _context())
        )
    finally:
        await _close_server(server.server)

    assert result.status == "success"
    assert result.output.get("status") == "success"
    assert result.output.get("provider_id") == "w-claim-1"
    assert server.request_count == 1


# ─── PR 5: three-gate enforcement + safe test endpoint ──────────────────────


@requires_postgres
@pytest.mark.asyncio
async def test_three_gate_missing_action_policy_denies_without_http_call(
    pg_session: AsyncSession,
    tmp_path: Path,
) -> None:
    hostname = "warranty-pr5-no-policy.local"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, hostname)
    server = await _start_server_or_skip(
        cert_path=cert_path,
        key_path=key_path,
    )
    client_ctx = ssl.create_default_context(cafile=cert_path)

    proposal = _proposal(seed="pr5-no-policy", requires_execution=True)
    assert proposal.session_id is not None
    assert proposal.execution_id is not None
    await set_pg_rls_tenant(pg_session, _TENANT_ID)
    await _seed_tenant(pg_session)
    await _seed_postgres_warranty_channel(pg_session)
    await _seed_postgres_warranty_config(
        pg_session,
        endpoint_template=f"https://{hostname}:{_server_port(server.server)}/claims",
        endpoint_host=hostname,
    )
    await _seed_session(pg_session, session_id=proposal.session_id)

    runtime = await _orchestration_runtime(
        pg_session,
        ssl_context=client_ctx,
        ssrf_validator=_local_validator,
    )

    try:
        result = await _invoke_or_skip(
            runtime.execute_proposal_actions(
                proposal=proposal,
                execution_context=_orchestration_context(
                    session_id=proposal.session_id,
                    execution_id=proposal.execution_id,
                ),
                expected_tenant_id=_TENANT_ID,
            )
        )
    finally:
        await _close_server(server.server)

    assert len(result.outcomes) == 1
    assert result.outcomes[0].status == "denied"
    assert server.request_count == 0
    assert await _count_connector_invocations(pg_session) == 0


@requires_postgres
@pytest.mark.asyncio
async def test_three_gate_requires_execution_false_skips_connector_call(
    pg_session: AsyncSession,
    tmp_path: Path,
) -> None:
    hostname = "warranty-pr5-skip.local"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, hostname)
    server = await _start_server_or_skip(
        cert_path=cert_path,
        key_path=key_path,
    )
    client_ctx = ssl.create_default_context(cafile=cert_path)

    proposal = _proposal(seed="pr5-skip", requires_execution=False)
    assert proposal.session_id is not None
    assert proposal.execution_id is not None
    await set_pg_rls_tenant(pg_session, _TENANT_ID)
    await _seed_tenant(pg_session)
    await _seed_postgres_warranty_channel(pg_session)
    await _seed_postgres_warranty_config(
        pg_session,
        endpoint_template=f"https://{hostname}:{_server_port(server.server)}/claims",
        endpoint_host=hostname,
    )
    await _seed_policy(PostgresTenantConfigurationRepository(pg_session))
    await _seed_session(pg_session, session_id=proposal.session_id)

    runtime = await _orchestration_runtime(
        pg_session,
        ssl_context=client_ctx,
        ssrf_validator=_local_validator,
    )

    try:
        result = await _invoke_or_skip(
            runtime.execute_proposal_actions(
                proposal=proposal,
                execution_context=_orchestration_context(
                    session_id=proposal.session_id,
                    execution_id=proposal.execution_id,
                ),
                expected_tenant_id=_TENANT_ID,
            )
        )
    finally:
        await _close_server(server.server)

    assert result.outcomes == ()
    assert server.request_count == 0
    assert await _count_connector_invocations(pg_session) == 0


@requires_postgres
@pytest.mark.asyncio
async def test_three_gate_all_present_executes_warranty_connector(
    pg_session: AsyncSession,
    tmp_path: Path,
) -> None:
    hostname = "warranty-pr5-exec.local"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, hostname)
    server = await _start_server_or_skip(
        cert_path=cert_path,
        key_path=key_path,
    )
    client_ctx = ssl.create_default_context(cafile=cert_path)

    proposal = _proposal(seed="pr5-exec", requires_execution=True)
    assert proposal.session_id is not None
    assert proposal.execution_id is not None
    await set_pg_rls_tenant(pg_session, _TENANT_ID)
    await _seed_tenant(pg_session)
    await _seed_postgres_warranty_channel(pg_session)
    await _seed_postgres_warranty_config(
        pg_session,
        endpoint_template=f"https://{hostname}:{_server_port(server.server)}/claims",
        endpoint_host=hostname,
    )
    await _seed_policy(PostgresTenantConfigurationRepository(pg_session))
    await _seed_session(pg_session, session_id=proposal.session_id)

    runtime = await _orchestration_runtime(
        pg_session,
        ssl_context=client_ctx,
        ssrf_validator=_local_validator,
    )

    try:
        result = await _invoke_or_skip(
            runtime.execute_proposal_actions(
                proposal=proposal,
                execution_context=_orchestration_context(
                    session_id=proposal.session_id,
                    execution_id=proposal.execution_id,
                ),
                expected_tenant_id=_TENANT_ID,
            )
        )
    finally:
        await _close_server(server.server)

    assert len(result.outcomes) == 1
    assert result.outcomes[0].status == "executed"
    assert server.request_count == 1
    assert server.effect_count == 1
    assert await _count_connector_invocations(pg_session) == 1


@requires_postgres
@pytest.mark.asyncio
async def test_connector_test_endpoint_validates_tls_without_transaction(
    pg_session: AsyncSession,
    tmp_path: Path,
) -> None:
    hostname = "warranty-pr5-test-endpoint.local"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, hostname)
    server = await _start_server_or_skip(
        cert_path=cert_path,
        key_path=key_path,
    )
    client_ctx = ssl.create_default_context(cafile=cert_path)

    await set_pg_rls_tenant(pg_session, _TENANT_ID)
    await _seed_tenant(pg_session)
    await _seed_postgres_warranty_channel(pg_session)
    await _seed_postgres_warranty_config(
        pg_session,
        endpoint_template=f"https://{hostname}:{_server_port(server.server)}/claims",
        endpoint_host=hostname,
    )

    try:
        async with _connector_test_client(
            pg_session,
            ssl_context=client_ctx,
            ssrf_validator=_local_validator,
        ) as client:
            response = await client.post(
                f"/api/v1/tenant/{_TENANT_ID}/connectors/{_WARRANTY_TOOL}/test",
                headers=_router_headers(),
            )
    finally:
        await _close_server(server.server)

    assert response.status_code == 200
    assert response.json() == {
        "reachable": True,
        "config_valid": True,
        "validated_host": hostname,
        "tls_verified": True,
        "http_probe": "skipped",
    }
    assert server.request_count == 0
    assert server.effect_count == 0
    assert await _count_connector_invocations(pg_session) == 0
    assert "sandbox-warranty-token" not in response.text
    assert "auth_header" not in response.text


@requires_postgres
@pytest.mark.asyncio
async def test_connector_test_endpoint_blocks_private_url_without_connection(
    pg_session: AsyncSession,
    tmp_path: Path,
) -> None:
    hostname = "127.0.0.1"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, "warranty-pr5-private.local")
    server = await _start_server_or_skip(
        cert_path=cert_path,
        key_path=key_path,
    )

    await set_pg_rls_tenant(pg_session, _TENANT_ID)
    await _seed_tenant(pg_session)
    await _seed_postgres_warranty_config(
        pg_session,
        endpoint_template=f"https://{hostname}:{_server_port(server.server)}/claims",
        endpoint_host=hostname,
    )

    try:
        async with _connector_test_client(pg_session) as client:
            response = await client.post(
                f"/api/v1/tenant/{_TENANT_ID}/connectors/{_WARRANTY_TOOL}/test",
                headers=_router_headers(),
            )
    finally:
        await _close_server(server.server)

    assert response.status_code == 200
    assert response.json() == {
        "reachable": False,
        "config_valid": False,
        "validated_host": None,
        "tls_verified": False,
        "http_probe": "skipped",
    }
    assert server.request_count == 0
    assert await _count_connector_invocations(pg_session) == 0


@requires_postgres
@pytest.mark.asyncio
async def test_connector_test_endpoint_requires_connector_write_capability(
    pg_session: AsyncSession,
) -> None:
    await set_pg_rls_tenant(pg_session, _TENANT_ID)
    await _seed_tenant(pg_session)
    await _seed_postgres_warranty_config(
        pg_session,
        endpoint_template="https://warranty.example.com/claims",
        endpoint_host="warranty.example.com",
    )

    async with _connector_test_client(pg_session) as client:
        response = await client.post(
            f"/api/v1/tenant/{_TENANT_ID}/connectors/{_WARRANTY_TOOL}/test",
            headers=_router_headers("empty"),
        )

    assert response.status_code == 403


# ─── Credential helper ────────────────────────────────────────────────────────


class _CredentialRuntime:
    def __init__(self) -> None:
        self.calls = 0

    async def load_channel_credentials(
        self,
        *,
        tenant_id: str,
        channel_type: TenantChannelType,
    ) -> dict[str, Any]:
        self.calls += 1
        return {"auth_header": "Bearer test-warranty-token"}
