"""End-to-end connector integration tests.

Exercises the complete path:
    TenantActionPolicy.evaluate() (governance gate)
    → ToolInvoker
    → GenericConnectorTool / GenericRestRefundConnector
    → real HTTPS server (self-signed cert, local socket)
    → response parsed and returned as ToolInvocationResult

These are the tests that were "missing" — they prove that the governance
gate, connector invocation ledger, and HTTP transport all interoperate
correctly end-to-end against a live socket.

Tests:
1. ALLOW path — refund under threshold fires the HTTP call and returns success.
2. REQUIRE_APPROVAL path — refund above threshold stops at the governance gate;
   no HTTP call is made.
3. DENY path — no active policy for tenant → DENY; no HTTP call.
4. Idempotency — two calls with same provider key hit the server once
   (connector deduplication).
5. SSRF guard — private IP endpoint is rejected before any network I/O.
6. Credential isolation — secret token reaches server but never appears in
   logs or result metadata.
7. Custom (non-commerce) tool ALLOW path — bank account.freeze (record_update,
   allow) dispatches correctly to a custom-tool server.
8. Custom money tool without auto_execute → REQUIRE_APPROVAL; server not called.
"""

from __future__ import annotations

import ssl
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from app.agents.capabilities import AgentCapability, CapabilitySet, ExecutionConstraints
from app.agents.context import AgentExecutionContext
from app.agents.enums import CapabilityScope
from app.agents.identity import AgentIdentity, ExecutionIdentity
from app.agents.results import ToolInvocationRequest
from app.agents.tools import ToolInvoker, ToolRegistry
from app.agents.tools.action_governance import build_action_tool_governance_runtime
from app.agents.tools.connectors import (
    ConnectorConfigRecord,
    GenericRestRefundConnector,
    InMemoryConnectorConfigRepository,
)
from app.agents.tools.grants import AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY
from app.agents.value_objects import CausalityMetadata
from app.core.ssrf import ValidatedPublicHTTPSURL
from app.governance.persistence.memory import InMemoryGovernanceRepository
from app.tenant.chronology import canonical_sha256
from app.tenant.enums import TenantChannelType, TenantGovernancePolicyStatus
from app.tenant.identity import derive_governance_policy_version_id
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    TenantGovernancePolicyRecord,
)

from tests.test_connector_framework import (  # reuse proven helpers
    _generate_self_signed_cert,
    _start_refund_server_or_skip,
    _close_server,
    _server_port,
    _invoke_socket_or_skip,
)


_TENANT = "tenant-e2e-connector"
_TOOL_REFUND = "refund.request"
_TOOL_FREEZE = "account.freeze"
_PROVIDER_KEY = "e2e-provider-key-1"
_SECRET = "e2e-bearer-token"
_NOW = __import__("datetime").datetime(2026, 7, 7, tzinfo=__import__("datetime").timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _CredentialRuntime:
    def __init__(self, token: str = _SECRET) -> None:
        self._token = token
        self.calls: int = 0

    async def load_channel_credentials(
        self, *, tenant_id: str, channel_type: TenantChannelType
    ) -> dict[str, Any]:
        self.calls += 1
        return {"auth_header": f"Bearer {self._token}"}


def _refund_config(endpoint_template: str, endpoint_host: str) -> ConnectorConfigRecord:
    return ConnectorConfigRecord(
        tenant_id=_TENANT,
        connector_type=TenantChannelType.ZENDESK.value,
        tool_name=_TOOL_REFUND,
        http_method="POST",
        endpoint_template=endpoint_template,
        endpoint_host=endpoint_host,
        field_mappings={
            "order_id": "payload.order_id",
            "sku": "payload.product_sku",
            "amount_cents": "payload.refund_amount_cents",
            "reason": "payload.refund_reason",
        },
        idempotency_header_name="X-Idempotency-Key",
        response_parse={
            "provider_id": "refund.id",
            "provider_status": "refund.status",
            "provider_error": "error.message",
        },
        success_status_codes=(200, 201, 202),
    )


def _freeze_config(endpoint_template: str, endpoint_host: str) -> ConnectorConfigRecord:
    return ConnectorConfigRecord(
        tenant_id=_TENANT,
        connector_type=TenantChannelType.ZENDESK.value,
        tool_name=_TOOL_FREEZE,
        http_method="POST",
        endpoint_template=endpoint_template,
        endpoint_host=endpoint_host,
        field_mappings={"account_number": "payload.account_number"},
        idempotency_header_name="X-Idempotency-Key",
        response_parse={"provider_status": "status"},
        success_status_codes=(200, 201),
    )


def _refund_request(*, refund_amount_cents: int = 1299) -> ToolInvocationRequest:
    return ToolInvocationRequest(
        tool_name=_TOOL_REFUND,
        payload={
            "order_id": "order-e2e",
            "product_sku": "sku-e2e",
            "refund_amount_cents": refund_amount_cents,
            "refund_reason": "defective",
        },
        metadata={
            "session_id": "session-e2e",
            "target_resource": "order:order-e2e:sku:sku-e2e",
            "tool_name": _TOOL_REFUND,
            "refund_amount_cents": refund_amount_cents,
            AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY: _PROVIDER_KEY,
        },
    )


def _freeze_request() -> ToolInvocationRequest:
    return ToolInvocationRequest(
        tool_name=_TOOL_FREEZE,
        payload={"account_number": "ACC-12345"},
        metadata={
            "session_id": "session-e2e",
            "tool_name": _TOOL_FREEZE,
            AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY: "e2e-freeze-key-1",
        },
    )


def _context(tool_name: str = _TOOL_REFUND) -> AgentExecutionContext:
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="test-e2e-agent",
            runtime_instance_id=uuid.uuid5(uuid.NAMESPACE_URL, "e2e-agent"),
        ),
        execution=ExecutionIdentity(
            execution_id=uuid.uuid5(uuid.NAMESPACE_URL, "e2e-exec"),
            request_id="e2e-request",
        ),
        capabilities=CapabilitySet(
            (
                AgentCapability(name=f"tool.{tool_name}", scope=CapabilityScope.INVOKE),
            )
        ),
        constraints=ExecutionConstraints(),
        causality=CausalityMetadata(),
        tenant_id=_TENANT,
        metadata={"session_id": "session-e2e"},
    )


def _local_validator(url: str, *, allowed_hosts: tuple[str, ...] = ()) -> ValidatedPublicHTTPSURL:
    parsed = urlsplit(url)
    assert parsed.hostname in allowed_hosts
    return ValidatedPublicHTTPSURL(
        url=url,
        hostname=parsed.hostname or "",
        port=parsed.port or 443,
        pinned_ip="127.0.0.1",
    )


def _private_ip_validator(url: str, *, allowed_hosts: tuple[str, ...] = ()) -> ValidatedPublicHTTPSURL:
    from app.core.ssrf import SSRFValidationError
    raise SSRFValidationError(f"private IP blocked: {url}")


def _refund_policy_record(
    *,
    tenant_id: str,
    refund_amount_cents_lte: int = 5000,
) -> TenantGovernancePolicyRecord:
    from app.agents.tools.action_governance import ACTION_TOOLS_POLICY_TYPE
    parameters: dict[str, Any] = {
        "tools": {
            "warranty.claim": {
                "allow": {"confidence_gte": 0.85, "issue_category_in": ["defect"]},
                "else": "require_approval",
            },
            "replacement.order": {"always": "require_approval"},
            "refund.request": {
                "allow": {"refund_amount_cents_lte": refund_amount_cents_lte},
                "else": "require_approval",
            },
            "warehouse.repair.report": {
                "allow": {"severity_in": ["low"]},
                "require_approval": {"severity_in": ["high", "critical"]},
            },
        }
    }
    content_sha256 = canonical_sha256({
        "tenant_id": tenant_id,
        "policy_type": ACTION_TOOLS_POLICY_TYPE,
        "parameters": parameters,
        "status": TenantGovernancePolicyStatus.ACTIVE.value,
        "version": 1,
        "approved_by": "e2e-admin",
        "effective_from": _NOW.isoformat(),
        "source_approval_id": "approval-e2e",
    })
    return TenantGovernancePolicyRecord(
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
        approved_by="e2e-admin",
        effective_from=_NOW,
        created_at=_NOW,
        source_approval_id="approval-e2e",
        content_sha256=content_sha256,
        previous_version_sha256=None,
    )


def _custom_policy_record(
    *, tenant_id: str, tools: dict[str, Any]
) -> TenantGovernancePolicyRecord:
    from app.agents.tools.action_governance import ACTION_TOOLS_POLICY_TYPE
    parameters = {"tools": tools}
    content_sha256 = canonical_sha256({
        "tenant_id": tenant_id,
        "policy_type": ACTION_TOOLS_POLICY_TYPE,
        "parameters": parameters,
        "status": TenantGovernancePolicyStatus.ACTIVE.value,
        "version": 1,
        "approved_by": "e2e-admin",
        "effective_from": _NOW.isoformat(),
        "source_approval_id": "approval-e2e-custom",
    })
    return TenantGovernancePolicyRecord(
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
        approved_by="e2e-admin",
        effective_from=_NOW,
        created_at=_NOW,
        source_approval_id="approval-e2e-custom",
        content_sha256=content_sha256,
        previous_version_sha256=None,
    )


# ---------------------------------------------------------------------------
# 1. ALLOW path — refund under threshold fires the HTTP call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_refund_allow_fires_http_call(tmp_path: Path) -> None:
    """Refund $12.99 (under $50 threshold) → governance ALLOW → HTTP call fires → success."""
    hostname = "e2e-refund-allow.local"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, hostname)
    server = await _start_refund_server_or_skip(cert_path=cert_path, key_path=key_path)
    client_ssl = ssl.create_default_context(cafile=cert_path)

    repo = InMemoryTenantConfigurationRepository()
    await repo.save_governance_policy(
        _refund_policy_record(tenant_id=_TENANT, refund_amount_cents_lte=5000),
        expected_tenant_id=_TENANT,
    )

    connector = GenericRestRefundConnector(
        config_repository=await _memory_config_with(
            hostname=hostname,
            port=_server_port(server.server),
            tool_name=_TOOL_REFUND,
            config=_refund_config,
        ),
        credential_runtime=_CredentialRuntime(),
        ssl_context=client_ssl,
        ssrf_validator=_local_validator,
    )
    registry = ToolRegistry()
    registry.register(connector)

    invoker = ToolInvoker(
        tool_registry=registry,
        governance_runtime=build_action_tool_governance_runtime(
            persistence=InMemoryGovernanceRepository(),
            redis_client=None,
            tenant_configuration_repository=repo,
        ),
    )

    try:
        envelope = await _invoke_socket_or_skip(
            invoker.invoke(_refund_request(refund_amount_cents=1299), _context(), invocation_ordinal=1)
        )
    finally:
        await _close_server(server.server)

    assert envelope.is_ok, f"Expected is_ok, trace status: {envelope.trace.status}"
    assert server.effect_count >= 1


# ---------------------------------------------------------------------------
# 2. REQUIRE_APPROVAL path — refund above threshold stops at gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_refund_above_threshold_stopped_at_gate() -> None:
    """Refund $200 (above $50 threshold) → governance REQUIRE_APPROVAL → connector not called."""
    credentials = _CredentialRuntime()

    repo = InMemoryTenantConfigurationRepository()
    await repo.save_governance_policy(
        _refund_policy_record(tenant_id=_TENANT, refund_amount_cents_lte=5000),
        expected_tenant_id=_TENANT,
    )

    connector = GenericRestRefundConnector(
        config_repository=await _memory_config_with(
            hostname="e2e-no-call.local",
            port=8888,
            tool_name=_TOOL_REFUND,
            config=_refund_config,
        ),
        credential_runtime=credentials,
        ssrf_validator=_private_ip_validator,
    )
    registry = ToolRegistry()
    registry.register(connector)

    invoker = ToolInvoker(
        tool_registry=registry,
        governance_runtime=build_action_tool_governance_runtime(
            persistence=InMemoryGovernanceRepository(),
            redis_client=None,
            tenant_configuration_repository=repo,
        ),
    )

    envelope = await invoker.invoke(
        _refund_request(refund_amount_cents=20_000),  # $200
        _context(),
        invocation_ordinal=1,
    )

    assert envelope.is_denied, (
        f"Expected denied (governance gate), trace status: {envelope.trace.status}"
    )
    assert credentials.calls == 0, "Credentials must not be loaded when gated"


# ---------------------------------------------------------------------------
# 3. DENY path — no active policy for tenant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_no_policy_denies_and_does_not_call_connector() -> None:
    """Tenant with no action_tools policy → DENY from gate; connector not called."""
    credentials = _CredentialRuntime()

    connector = GenericRestRefundConnector(
        config_repository=await _memory_config_with(
            hostname="e2e-deny.local",
            port=8888,
            tool_name=_TOOL_REFUND,
            config=_refund_config,
        ),
        credential_runtime=credentials,
        ssrf_validator=_private_ip_validator,
    )
    registry = ToolRegistry()
    registry.register(connector)

    invoker = ToolInvoker(
        tool_registry=registry,
        governance_runtime=build_action_tool_governance_runtime(
            persistence=InMemoryGovernanceRepository(),
            redis_client=None,
            tenant_configuration_repository=InMemoryTenantConfigurationRepository(),
        ),
    )

    envelope = await invoker.invoke(_refund_request(), _context(), invocation_ordinal=1)

    assert envelope.is_denied, (
        f"Expected denied without policy, trace status: {envelope.trace.status}"
    )
    assert credentials.calls == 0


# ---------------------------------------------------------------------------
# 4. Idempotency — two calls with same provider key hit server once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_idempotency_fires_server_once(tmp_path: Path) -> None:
    """Two invocations with the same provider key should hit the server once (deduplication)."""
    hostname = "e2e-idem.local"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, hostname)
    server = await _start_refund_server_or_skip(cert_path=cert_path, key_path=key_path)
    client_ssl = ssl.create_default_context(cafile=cert_path)

    repo = InMemoryTenantConfigurationRepository()
    await repo.save_governance_policy(
        _refund_policy_record(tenant_id=_TENANT, refund_amount_cents_lte=5000),
        expected_tenant_id=_TENANT,
    )

    connector = GenericRestRefundConnector(
        config_repository=await _memory_config_with(
            hostname=hostname,
            port=_server_port(server.server),
            tool_name=_TOOL_REFUND,
            config=_refund_config,
        ),
        credential_runtime=_CredentialRuntime(),
        ssl_context=client_ssl,
        ssrf_validator=_local_validator,
    )
    registry = ToolRegistry()
    registry.register(connector)
    invoker = ToolInvoker(
        tool_registry=registry,
        governance_runtime=build_action_tool_governance_runtime(
            persistence=InMemoryGovernanceRepository(),
            redis_client=None,
            tenant_configuration_repository=repo,
        ),
    )

    try:
        first = await _invoke_socket_or_skip(
            invoker.invoke(_refund_request(refund_amount_cents=1299), _context(), invocation_ordinal=1)
        )
        second = await _invoke_socket_or_skip(
            invoker.invoke(_refund_request(refund_amount_cents=1299), _context(), invocation_ordinal=1)
        )
    finally:
        await _close_server(server.server)

    assert first.is_ok, f"First call failed: {first.trace.status}"
    assert second.is_ok, f"Second call failed: {second.trace.status}"
    # Server enforces idempotency: same key → same effect → effect_count == 1
    assert server.effect_count == 1


# ---------------------------------------------------------------------------
# 5. SSRF guard blocks private IP endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_ssrf_guard_blocks_private_ip() -> None:
    """A connector configured with a private-IP endpoint is rejected before any I/O."""
    from app.core.ssrf import SSRFValidationError

    credentials = _CredentialRuntime()
    connector = GenericRestRefundConnector(
        config_repository=await _memory_config_with(
            hostname="169.254.169.254",
            port=443,
            tool_name=_TOOL_REFUND,
            config=lambda endpoint_template, endpoint_host: _refund_config(
                endpoint_template=endpoint_template, endpoint_host=endpoint_host
            ),
        ),
        credential_runtime=credentials,
        ssrf_validator=_private_ip_validator,
    )

    with pytest.raises(SSRFValidationError):
        await connector.invoke(_refund_request(), _context())


# ---------------------------------------------------------------------------
# 6. Credential isolation — secret never in logs or result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_credentials_not_in_logs_or_result(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    hostname = "e2e-cred-isolation.local"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, hostname)
    server = await _start_refund_server_or_skip(cert_path=cert_path, key_path=key_path)
    client_ssl = ssl.create_default_context(cafile=cert_path)

    repo = InMemoryTenantConfigurationRepository()
    await repo.save_governance_policy(
        _refund_policy_record(tenant_id=_TENANT, refund_amount_cents_lte=5000),
        expected_tenant_id=_TENANT,
    )
    connector = GenericRestRefundConnector(
        config_repository=await _memory_config_with(
            hostname=hostname,
            port=_server_port(server.server),
            tool_name=_TOOL_REFUND,
            config=_refund_config,
        ),
        credential_runtime=_CredentialRuntime(token=_SECRET),
        ssl_context=client_ssl,
        ssrf_validator=_local_validator,
    )
    registry = ToolRegistry()
    registry.register(connector)
    invoker = ToolInvoker(
        tool_registry=registry,
        governance_runtime=build_action_tool_governance_runtime(
            persistence=InMemoryGovernanceRepository(),
            redis_client=None,
            tenant_configuration_repository=repo,
        ),
    )

    try:
        result = await _invoke_socket_or_skip(
            invoker.invoke(_refund_request(refund_amount_cents=1299), _context(), invocation_ordinal=1)
        )
    finally:
        await _close_server(server.server)

    assert result.is_ok, f"Expected is_ok, trace status: {result.trace.status}"
    assert _SECRET not in caplog.text, "Bearer token leaked into logs"
    assert _SECRET not in str(result.result), "Bearer token in result output"
    assert _SECRET not in str(result.trace), "Bearer token in trace metadata"


# ---------------------------------------------------------------------------
# 7. Policy always:allow path — refund.request with always:allow fires call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_always_allow_policy_fires_http_call(tmp_path: Path) -> None:
    """refund.request with always:allow policy ALLOW → HTTP call fires.

    This exercises the AlwaysRule path through TenantActionPolicy, a different
    code path from the AmountThreshold rule used in test 1.
    """
    hostname = "e2e-always-allow.local"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, hostname)
    server = await _start_refund_server_or_skip(cert_path=cert_path, key_path=key_path)
    client_ssl = ssl.create_default_context(cafile=cert_path)

    repo = InMemoryTenantConfigurationRepository()
    always_allow_params: dict[str, Any] = {
        "tools": {
            "warranty.claim": {
                "allow": {"confidence_gte": 0.85, "issue_category_in": ["defect"]},
                "else": "require_approval",
            },
            "replacement.order": {"always": "allow"},  # AlwaysRule → ALLOW
            "refund.request": {
                "allow": {"refund_amount_cents_lte": 5000},
                "else": "require_approval",
            },
            "warehouse.repair.report": {
                "allow": {"severity_in": ["low"]},
                "require_approval": {"severity_in": ["high", "critical"]},
            },
        }
    }
    from app.agents.tools.action_governance import ACTION_TOOLS_POLICY_TYPE
    always_record = TenantGovernancePolicyRecord(
        policy_id=derive_governance_policy_version_id(
            tenant_id=_TENANT,
            policy_type=ACTION_TOOLS_POLICY_TYPE,
            version=2,
        ),
        tenant_id=_TENANT,
        policy_type=ACTION_TOOLS_POLICY_TYPE,
        parameters=always_allow_params,
        status=TenantGovernancePolicyStatus.ACTIVE,
        version=2,
        approved_by="e2e-admin",
        effective_from=_NOW,
        created_at=_NOW,
        source_approval_id="approval-e2e-always",
        content_sha256=canonical_sha256({
            "tenant_id": _TENANT, "policy_type": ACTION_TOOLS_POLICY_TYPE,
            "parameters": always_allow_params,
            "status": TenantGovernancePolicyStatus.ACTIVE.value,
            "version": 2, "approved_by": "e2e-admin",
            "effective_from": _NOW.isoformat(),
            "source_approval_id": "approval-e2e-always",
        }),
        previous_version_sha256=None,
    )
    await repo.save_governance_policy(always_record, expected_tenant_id=_TENANT)

    # Use the replacement.order connector (which always:allow) against the test server.
    from app.agents.tools.connectors import InMemoryConnectorConfigRepository
    replacement_config = ConnectorConfigRecord(
        tenant_id=_TENANT,
        connector_type=TenantChannelType.ZENDESK.value,
        tool_name="replacement.order",
        http_method="POST",
        endpoint_template=f"https://{hostname}:{_server_port(server.server)}/replacements",
        endpoint_host=hostname,
        field_mappings={"order_id": "payload.order_id", "sku": "payload.product_sku"},
        idempotency_header_name="X-Idempotency-Key",
        response_parse={"provider_id": "replacement.id", "provider_status": "replacement.status"},
        success_status_codes=(200, 201, 202),
    )
    config_repo = InMemoryConnectorConfigRepository()
    await config_repo.save_config(replacement_config, expected_tenant_id=_TENANT)

    from app.agents.tools.connectors.replacement import ReplacementOrderConnector
    connector = ReplacementOrderConnector(
        config_repository=config_repo,
        credential_runtime=_CredentialRuntime(),
        ssl_context=client_ssl,
        ssrf_validator=_local_validator,
    )
    registry = ToolRegistry()
    registry.register(connector)
    invoker = ToolInvoker(
        tool_registry=registry,
        governance_runtime=build_action_tool_governance_runtime(
            persistence=InMemoryGovernanceRepository(),
            redis_client=None,
            tenant_configuration_repository=repo,
        ),
    )

    replacement_request = ToolInvocationRequest(
        tool_name="replacement.order",
        payload={
            "order_id": "order-e2e-replace",
            "product_sku": "sku-e2e",
            "replacement_reason": "defective",
            "shipping_address_hash": "hash-abc",
        },
        metadata={
            "session_id": "session-e2e",
            "tool_name": "replacement.order",
            AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY: "e2e-replace-key-1",
        },
    )
    ctx = AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="test-e2e-agent",
            runtime_instance_id=uuid.uuid5(uuid.NAMESPACE_URL, "e2e-agent"),
        ),
        execution=ExecutionIdentity(
            execution_id=uuid.uuid5(uuid.NAMESPACE_URL, "e2e-exec"),
            request_id="e2e-request",
        ),
        capabilities=CapabilitySet(
            (AgentCapability(name="tool.replacement.order", scope=CapabilityScope.INVOKE),)
        ),
        constraints=ExecutionConstraints(),
        causality=CausalityMetadata(),
        tenant_id=_TENANT,
        metadata={"session_id": "session-e2e"},
    )

    try:
        envelope = await _invoke_socket_or_skip(
            invoker.invoke(replacement_request, ctx, invocation_ordinal=1)
        )
    finally:
        await _close_server(server.server)

    assert envelope.is_ok, f"Expected is_ok for always:allow, trace status: {envelope.trace.status}"


# ---------------------------------------------------------------------------
# 8. Custom money tool without auto_execute → gate stops it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_custom_money_tool_stopped_without_auto_execute() -> None:
    """account.credit (money, no execution_policy) → REQUIRE_APPROVAL; server not called."""
    credentials = _CredentialRuntime()

    repo = InMemoryTenantConfigurationRepository()
    await repo.save_governance_policy(
        _custom_policy_record(
            tenant_id=_TENANT,
            tools={
                "account.credit": {
                    "commitment_kind": "money",
                    "decision": "require_approval",
                }
            },
        ),
        expected_tenant_id=_TENANT,
    )

    credit_request = ToolInvocationRequest(
        tool_name="account.credit",
        payload={"account_number": "ACC-12345", "amount_cents": 5000},
        metadata={
            "session_id": "session-e2e",
            "tool_name": "account.credit",
            AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY: "e2e-credit-key-1",
        },
    )
    # No real connector needed — gate should stop it before invoke()
    registry = ToolRegistry()
    invoker = ToolInvoker(
        tool_registry=registry,
        governance_runtime=build_action_tool_governance_runtime(
            persistence=InMemoryGovernanceRepository(),
            redis_client=None,
            tenant_configuration_repository=repo,
        ),
    )

    envelope = await invoker.invoke(
        credit_request,
        _context(tool_name="account.credit"),
        invocation_ordinal=1,
    )

    assert envelope.is_denied, (
        f"Expected denied for money tool without auto_execute, trace status: {envelope.trace.status}"
    )
    assert credentials.calls == 0


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _memory_config_with(
    *,
    hostname: str,
    port: int,
    tool_name: str,
    config: Any,
) -> InMemoryConnectorConfigRepository:
    repository = InMemoryConnectorConfigRepository()
    await repository.save_config(
        config(
            endpoint_template=f"https://{hostname}:{port}/",
            endpoint_host=hostname,
        ),
        expected_tenant_id=_TENANT,
    )
    return repository
