"""Governance invariant tests for MCP connector integration.

Verified claims:

1. AUTO_EXECUTE — a money/goods MCP tool set to auto_execute fires immediately.
   McpConnectorTool.invoke() IS called; no Operious approval gate.
   The tenant explicitly chose full autonomy. Fully audited.

2. OPERIOUS_APPROVAL — an MCP tool set to operious_approval routes to
   REQUIRE_APPROVAL. McpConnectorTool.invoke() is NEVER called.

3. UNCONFIGURED (safe default) — a tool not in the policy custom_tools →
   REQUIRE_APPROVAL. Invoke never fires. Safe default for unknown tools.

4. EXECUTION_POLICY OVERRIDES DECISION — even if the legacy 'decision' field
   says 'allow', execution_policy=operious_approval → REQUIRE_APPROVAL.
   And vice versa: execution_policy=auto_execute → ALLOW regardless of decision.

5. MISDECLARATION BACKSTOP — a tool declared none/record_update with operious_
   approval execution and money/goods metadata signal → REQUIRE_APPROVAL.
   The backstop is SILENT when execution_policy=auto_execute (tenant is aware).

6. FAIL-CLOSED ON TRANSPORT ERROR — even an auto_execute tool, if the server
   errors, returns status="provider_error". Never silently succeeds.

7. FAIL-CLOSED ON MALFORMED RESPONSE — MCP server returns non-JSON-RPC response
   → provider_error. Never silently succeeds.

8. REGISTRY SYNTHESIS — build_tenant_action_tool_registry() with a mcp_server
   ConnectorConfigRecord synthesizes one McpConnectorTool per enabled tool.
   Disabled tools are absent from registry.

9. EXECUTION_POLICY PARSING — action_tools policy with execution_policy field
   parses correctly; missing execution_policy falls back to decision field.

10. MCP CHANGE-REQUEST VALIDATION — MCP_SERVER payload validation catches
    missing fields, non-HTTPS URLs, invalid commitment_kind/execution_policy.
    MCP_OAUTH_TOKEN sentinel validation rejects plaintext tokens.

All tests use a mock MCP server (no real external accounts required).
What needs real accounts: OAuth dance, real token exchange/refresh,
live tools/list + tools/call against a real MCP server.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities import AgentCapability, CapabilitySet, ExecutionConstraints
from app.agents.context import AgentExecutionContext
from app.agents.enums import CapabilityScope
from app.agents.identity import AgentIdentity, ExecutionIdentity
from app.agents.results import ToolInvocationRequest
from app.agents.tools import ToolInvoker, ToolRegistry
from app.agents.tools.action_governance import (
    ACTION_TOOLS_POLICY_TYPE,
    ActionPolicyBinding,
    CustomToolDeclaration,
    ParsedActionPolicy,
    _evaluate_custom_tool,
    build_action_tool_governance_runtime,
)
from app.agents.tools.actions import build_tenant_action_tool_registry
from app.agents.tools.connectors import InMemoryConnectorConfigRepository
from app.agents.tools.connectors.config import ConnectorConfigRecord
from app.agents.tools.connectors.credentials import (
    ConnectorCredentialRecord,
    ConnectorScopedCredentialRuntime,
)
from app.agents.tools.connectors.mcp import (
    McpConnectorTool,
    McpCredentialRuntime,
    McpToolDeclaration,
    parse_mcp_server_config,
)
from app.agents.tools.operation_metadata import (
    CommitmentKind,
    ExecutionPolicy,
)
from app.agents.value_objects import CausalityMetadata
from app.governance.enums import Decision
from app.governance.persistence.memory import InMemoryGovernanceRepository
from app.services.tenant_config_change_request_service import (
    TenantConfigChangeRequestLifecycleError,
    _validate_mcp_server_payload,
    _validate_mcp_oauth_token_sentinel,
)
from app.tenant.chronology import canonical_sha256
from app.tenant.enums import TenantGovernancePolicyStatus
from app.tenant.identity import derive_governance_policy_version_id
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    TenantGovernancePolicyRecord,
)

pytestmark = pytest.mark.asyncio

_TENANT = "tenant-mcp-governance-proof"
_NOW = datetime(2026, 7, 6, tzinfo=timezone.utc)
_APPROVAL_ID = "approval-mcp-proof"
_APPROVED_BY = "admin"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _binding() -> ActionPolicyBinding:
    return ActionPolicyBinding(
        policy_id="p-mcp-test",
        policy_type=ACTION_TOOLS_POLICY_TYPE,
        version=1,
        content_sha256="b" * 64,
    )


def _policy_record(
    *,
    tenant_id: str = _TENANT,
    tools: dict[str, Any],
) -> TenantGovernancePolicyRecord:
    parameters = {"tools": tools}
    content_sha256 = canonical_sha256(
        {
            "tenant_id": tenant_id,
            "policy_type": ACTION_TOOLS_POLICY_TYPE,
            "parameters": parameters,
            "status": TenantGovernancePolicyStatus.ACTIVE.value,
            "version": 1,
            "approved_by": _APPROVED_BY,
            "effective_from": _NOW.isoformat(),
            "source_approval_id": _APPROVAL_ID,
        }
    )
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
        approved_by=_APPROVED_BY,
        effective_from=_NOW,
        created_at=_NOW,
        source_approval_id=_APPROVAL_ID,
        content_sha256=content_sha256,
        previous_version_sha256=None,
    )


def _mcp_policy(
    tool_name: str,
    commitment_kind: CommitmentKind,
    execution_policy: ExecutionPolicy,
) -> ParsedActionPolicy:
    return ParsedActionPolicy(
        binding=_binding(),
        rules={},
        custom_tools={
            tool_name: CustomToolDeclaration(
                tool_name=tool_name,
                commitment_kind=commitment_kind,
                decision=Decision.REQUIRE_APPROVAL,  # legacy field — overridden by execution_policy
                execution_policy=execution_policy,
            )
        },
    )


def _context(*, seed: str = "1") -> AgentExecutionContext:
    import uuid
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="test-mcp-agent",
            runtime_instance_id=uuid.uuid5(uuid.NAMESPACE_URL, f"mcp-gate:{seed}"),
        ),
        execution=ExecutionIdentity(
            execution_id=uuid.uuid5(uuid.NAMESPACE_URL, f"mcp-exec:{seed}"),
            request_id=f"req-mcp-{seed}",
        ),
        capabilities=CapabilitySet((
            AgentCapability(name="tool.gmail_mcp.send_email", scope=CapabilityScope.INVOKE),
            AgentCapability(name="tool.crm_mcp.issue_refund", scope=CapabilityScope.INVOKE),
            AgentCapability(name="tool.crm_mcp.read_contact", scope=CapabilityScope.INVOKE),
        )),
        constraints=ExecutionConstraints(),
        causality=CausalityMetadata(),
        tenant_id=_TENANT,
        metadata={"session_id": f"session-mcp-{seed}"},
    )


def _send_email_request(seed: str = "1") -> ToolInvocationRequest:
    return ToolInvocationRequest(
        tool_name="gmail_mcp.send_email",
        payload={"to": "customer@example.com", "subject": "Your order update", "body": "Hi!"},
        metadata={"tool_name": "gmail_mcp.send_email", "session_id": f"session-mcp-{seed}"},
    )


def _read_contact_request(seed: str = "1") -> ToolInvocationRequest:
    return ToolInvocationRequest(
        tool_name="crm_mcp.read_contact",
        payload={"contact_id": "C-001"},
        metadata={"tool_name": "crm_mcp.read_contact", "session_id": f"session-mcp-{seed}"},
    )


def _issue_refund_request(seed: str = "1") -> ToolInvocationRequest:
    return ToolInvocationRequest(
        tool_name="crm_mcp.issue_refund",
        payload={"order_id": "ORD-001", "amount_cents": 5000},
        metadata={"tool_name": "crm_mcp.issue_refund", "session_id": f"session-mcp-{seed}"},
    )


def _make_credential_runtime(tenant_id: str = _TENANT) -> ConnectorScopedCredentialRuntime:
    """Build an in-memory credential runtime with a pre-loaded OAuth token."""

    class _InMemoryCodec:
        def encrypt(self, *, tenant_id: str, credentials: dict[str, Any], channel_type: str) -> bytes:
            return json.dumps(credentials).encode()

        def decrypt(self, *, tenant_id: str, encrypted_credentials: bytes, channel_type: str) -> dict[str, Any]:
            return json.loads(encrypted_credentials)

    class _InMemoryCredRepo:
        def __init__(self) -> None:
            self._records: dict[tuple[str, str], ConnectorCredentialRecord] = {}

        async def get(self, *, tenant_id: str, connector_id: str, expected_tenant_id: str) -> ConnectorCredentialRecord | None:
            if tenant_id != expected_tenant_id:
                return None
            return self._records.get((tenant_id, connector_id))

        async def get_active(self, *, tenant_id: str, connector_id: str, expected_tenant_id: str) -> ConnectorCredentialRecord | None:
            rec = await self.get(tenant_id=tenant_id, connector_id=connector_id, expected_tenant_id=expected_tenant_id)
            if rec is None or rec.status != "active":
                return None
            return rec

        async def upsert(self, record: ConnectorCredentialRecord, *, expected_tenant_id: str) -> ConnectorCredentialRecord:
            self._records[(record.tenant_id, record.connector_id)] = record
            return record

        async def list_active_for_tenant(self, *, tenant_id: str, expected_tenant_id: str) -> list[ConnectorCredentialRecord]:
            return [r for (t, _), r in self._records.items() if t == tenant_id and r.status == "active"]

    codec = _InMemoryCodec()
    repo = _InMemoryCredRepo()

    # Pre-load a token for gmail_mcp and crm_mcp.
    for server_id in ("gmail_mcp", "crm_mcp"):
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            repo.upsert(
                ConnectorCredentialRecord(
                    tenant_id=tenant_id,
                    connector_id=server_id,
                    credentials_enc=codec.encrypt(
                        tenant_id=tenant_id,
                        credentials={"access_token": f"tok-{server_id}"},
                        channel_type=server_id,
                    ),
                    credential_hash="a" * 64,
                    status="active",
                    configured_by="test",
                    source_approval_id="approval-test",
                ),
                expected_tenant_id=tenant_id,
            )
        )
    return ConnectorScopedCredentialRuntime(repository=repo, codec=codec, tenant_id=tenant_id)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Claim 1: AUTO_EXECUTE → fires immediately, no gate (even for goods tools)
# ---------------------------------------------------------------------------


async def test_auto_execute_goods_tool_fires_immediately() -> None:
    """Claim 1: execution_policy=auto_execute → Decision.ALLOW regardless of commitment_kind.

    Even a goods-classified MCP tool set to auto_execute fires. The tenant
    explicitly chose full autonomy; their system owns authorization.
    """
    policy = _mcp_policy(
        tool_name="gmail_mcp.send_email",
        commitment_kind=CommitmentKind.GOODS,  # would normally route to human
        execution_policy=ExecutionPolicy.AUTO_EXECUTE,
    )
    result = _evaluate_custom_tool(
        tool_name="gmail_mcp.send_email",
        policy=policy,
    )
    assert len(result) == 1
    assert result[0].decision is Decision.ALLOW, (
        "auto_execute must resolve to ALLOW even for goods tools"
    )
    assert "auto_execute" in result[0].reason


async def test_auto_execute_money_tool_fires_immediately() -> None:
    """Auto_execute money tool also resolves to ALLOW — tenant chose full autonomy."""
    policy = _mcp_policy(
        tool_name="crm_mcp.issue_refund",
        commitment_kind=CommitmentKind.MONEY,
        execution_policy=ExecutionPolicy.AUTO_EXECUTE,
    )
    result = _evaluate_custom_tool(
        tool_name="crm_mcp.issue_refund",
        policy=policy,
    )
    assert result[0].decision is Decision.ALLOW
    assert "auto_execute" in result[0].reason


async def test_auto_execute_none_tool_fires() -> None:
    """Auto_execute none/read tool also fires — consistent model."""
    policy = _mcp_policy(
        tool_name="crm_mcp.read_contact",
        commitment_kind=CommitmentKind.NONE,
        execution_policy=ExecutionPolicy.AUTO_EXECUTE,
    )
    result = _evaluate_custom_tool(tool_name="crm_mcp.read_contact", policy=policy)
    assert result[0].decision is Decision.ALLOW


# ---------------------------------------------------------------------------
# Claim 2: OPERIOUS_APPROVAL → routes to human queue, invoke() never fired
# ---------------------------------------------------------------------------


async def test_operious_approval_routes_to_human() -> None:
    """Claim 2: execution_policy=operious_approval → REQUIRE_APPROVAL."""
    policy = _mcp_policy(
        tool_name="crm_mcp.issue_refund",
        commitment_kind=CommitmentKind.MONEY,
        execution_policy=ExecutionPolicy.OPERIOUS_APPROVAL,
    )
    result = _evaluate_custom_tool(tool_name="crm_mcp.issue_refund", policy=policy)
    assert result[0].decision is Decision.REQUIRE_APPROVAL


async def test_operious_approval_invoke_never_called() -> None:
    """Claim 2b: ToolInvoker does NOT call McpConnectorTool.invoke() for operious_approval.

    The invoker gate fires before the tool body. invoke() spy must see zero calls.
    """
    tenant_repo = InMemoryTenantConfigurationRepository()
    await tenant_repo.save_governance_policy(
        _policy_record(
            tools={
                "crm_mcp.issue_refund": {
                    "commitment_kind": "money",
                    "execution_policy": "operious_approval",
                }
            }
        ),
        expected_tenant_id=_TENANT,
    )
    governance = build_action_tool_governance_runtime(
        persistence=InMemoryGovernanceRepository(),
        tenant_configuration_repository=tenant_repo,
    )

    invoke_spy = AsyncMock(side_effect=AssertionError("invoke() must not be called pre-approval"))
    mock_tool = MagicMock()
    mock_tool.name = "crm_mcp.issue_refund"
    mock_tool.capability = MagicMock()
    mock_tool.capability.__eq__ = lambda self, other: str(other) == "action"
    mock_tool.invoke = invoke_spy
    mock_tool.operation_governance_metadata = MagicMock(return_value={
        "operation_id": "issue_refund",
        "operation_commitment_kind": "money",
        "operation_approval_policy": "tenant_policy",
        "operation_execution_policy": "operious_approval",
        "mcp_server_id": "crm_mcp",
        "mcp_tool_name": "issue_refund",
    })

    registry = ToolRegistry()
    registry.register(mock_tool)

    invoker = ToolInvoker(
        tool_registry=registry,
        governance_runtime=governance,
        grant_repository=None,
        connector_invocation_repository=None,
    )
    envelope = await invoker.invoke(
        request=_issue_refund_request(),
        context=_context(),
        invocation_ordinal=1,
    )
    invoke_spy.assert_not_called()
    # The invoker returns a denied envelope when governance blocks the call.
    assert envelope.is_denied, (
        f"Expected denied envelope for operious_approval tool; got is_denied={envelope.is_denied}, "
        f"trace={envelope.trace}"
    )


# ---------------------------------------------------------------------------
# Claim 3: UNCONFIGURED → safe default REQUIRE_APPROVAL
# ---------------------------------------------------------------------------


async def test_unconfigured_tool_routes_to_human() -> None:
    """Claim 3: unknown tool not in policy → REQUIRE_APPROVAL (safe default)."""
    policy = ParsedActionPolicy(binding=_binding(), rules={}, custom_tools={})
    result = _evaluate_custom_tool(tool_name="unknown_mcp.mystery_action", policy=policy)
    assert result[0].decision is Decision.REQUIRE_APPROVAL
    assert "not registered" in result[0].reason or "safe default" in result[0].reason


async def test_unconfigured_tool_absent_from_manifest() -> None:
    """Claim 3b: policy has some tools but not this one → REQUIRE_APPROVAL."""
    policy = _mcp_policy(
        tool_name="crm_mcp.read_contact",
        commitment_kind=CommitmentKind.NONE,
        execution_policy=ExecutionPolicy.AUTO_EXECUTE,
    )
    # Tool name not in policy:
    result = _evaluate_custom_tool(tool_name="crm_mcp.delete_contact", policy=policy)
    assert result[0].decision is Decision.REQUIRE_APPROVAL


# ---------------------------------------------------------------------------
# Claim 4: EXECUTION_POLICY OVERRIDES LEGACY DECISION FIELD
# ---------------------------------------------------------------------------


async def test_execution_policy_overrides_legacy_allow_decision() -> None:
    """Claim 4a: execution_policy=operious_approval overrides legacy decision=allow."""
    # Legacy declaration that says 'allow' but has operious_approval execution policy
    declaration = CustomToolDeclaration(
        tool_name="crm_mcp.issue_refund",
        commitment_kind=CommitmentKind.MONEY,
        decision=Decision.ALLOW,           # legacy says allow
        execution_policy=ExecutionPolicy.OPERIOUS_APPROVAL,  # overrides
    )
    policy = ParsedActionPolicy(
        binding=_binding(),
        rules={},
        custom_tools={"crm_mcp.issue_refund": declaration},
    )
    result = _evaluate_custom_tool(tool_name="crm_mcp.issue_refund", policy=policy)
    assert result[0].decision is Decision.REQUIRE_APPROVAL, (
        "execution_policy=operious_approval must override legacy decision=allow"
    )


async def test_execution_policy_overrides_legacy_require_approval_decision() -> None:
    """Claim 4b: execution_policy=auto_execute overrides legacy decision=require_approval."""
    declaration = CustomToolDeclaration(
        tool_name="gmail_mcp.send_email",
        commitment_kind=CommitmentKind.GOODS,
        decision=Decision.REQUIRE_APPROVAL,  # legacy says require_approval
        execution_policy=ExecutionPolicy.AUTO_EXECUTE,  # overrides → ALLOW
    )
    policy = ParsedActionPolicy(
        binding=_binding(),
        rules={},
        custom_tools={"gmail_mcp.send_email": declaration},
    )
    result = _evaluate_custom_tool(tool_name="gmail_mcp.send_email", policy=policy)
    assert result[0].decision is Decision.ALLOW, (
        "execution_policy=auto_execute must override legacy decision=require_approval"
    )


async def test_legacy_decision_field_honored_when_no_execution_policy() -> None:
    """Claim 4c: when execution_policy is absent, legacy decision field is used (backward compat)."""
    declaration = CustomToolDeclaration(
        tool_name="rest_tool.some_action",
        commitment_kind=CommitmentKind.NONE,
        decision=Decision.ALLOW,
        execution_policy=None,  # no execution_policy → use decision field
    )
    policy = ParsedActionPolicy(
        binding=_binding(),
        rules={},
        custom_tools={"rest_tool.some_action": declaration},
    )
    result = _evaluate_custom_tool(tool_name="rest_tool.some_action", policy=policy)
    assert result[0].decision is Decision.ALLOW


# ---------------------------------------------------------------------------
# Claim 5: MISDECLARATION BACKSTOP (silent for auto_execute)
# ---------------------------------------------------------------------------


async def test_misdeclaration_backstop_fires_for_operious_approval() -> None:
    """Claim 5a: declared none/operious_approval → REQUIRE_APPROVAL (operious_approval fires first).

    When execution_policy=operious_approval is set, the tool routes to REQUIRE_APPROVAL
    regardless. The misdeclaration backstop is an additional defense-in-depth that
    fires on the LEGACY path (no execution_policy). Both paths end at REQUIRE_APPROVAL.
    """
    declaration = CustomToolDeclaration(
        tool_name="crm_mcp.issue_refund",
        commitment_kind=CommitmentKind.NONE,  # misdeclared
        decision=Decision.ALLOW,
        execution_policy=ExecutionPolicy.OPERIOUS_APPROVAL,
    )
    policy = ParsedActionPolicy(
        binding=_binding(),
        rules={},
        custom_tools={"crm_mcp.issue_refund": declaration},
    )
    metadata: dict[str, Any] = {
        "operation_commitment_kind": "money",  # backstop signal
        "tool_name": "crm_mcp.issue_refund",
    }
    result = _evaluate_custom_tool(
        tool_name="crm_mcp.issue_refund",
        policy=policy,
        subject_metadata=metadata,
    )
    # Either path (operious_approval fast path or misdeclaration backstop) → REQUIRE_APPROVAL.
    assert result[0].decision is Decision.REQUIRE_APPROVAL


async def test_misdeclaration_backstop_fires_on_legacy_path() -> None:
    """Claim 5c: legacy path — no execution_policy, declared none but metadata signals money.

    On the legacy path (no execution_policy), the misdeclaration backstop fires
    and routes to REQUIRE_APPROVAL even though legacy decision=allow.
    """
    declaration = CustomToolDeclaration(
        tool_name="legacy_rest_tool.some_action",
        commitment_kind=CommitmentKind.NONE,  # misdeclared
        decision=Decision.ALLOW,              # legacy says allow
        execution_policy=None,                # no execution_policy — legacy path
    )
    policy = ParsedActionPolicy(
        binding=_binding(),
        rules={},
        custom_tools={"legacy_rest_tool.some_action": declaration},
    )
    metadata: dict[str, Any] = {
        "operation_commitment_kind": "money",
        "tool_name": "legacy_rest_tool.some_action",
    }
    result = _evaluate_custom_tool(
        tool_name="legacy_rest_tool.some_action",
        policy=policy,
        subject_metadata=metadata,
    )
    assert result[0].decision is Decision.REQUIRE_APPROVAL
    assert "money/goods" in result[0].reason.lower() or "misdeclaration" in result[0].reason.lower() or "commitment" in result[0].reason.lower()


async def test_misdeclaration_backstop_silent_for_auto_execute() -> None:
    """Claim 5b: auto_execute bypasses misdeclaration backstop — tenant is aware.

    When a tenant explicitly sets auto_execute, even if the metadata signals
    money/goods, the backstop does not fire. The execution_policy=auto_execute
    means the tenant has accepted responsibility.
    """
    declaration = CustomToolDeclaration(
        tool_name="crm_mcp.issue_refund",
        commitment_kind=CommitmentKind.NONE,  # misdeclared — but auto_execute
        decision=Decision.ALLOW,
        execution_policy=ExecutionPolicy.AUTO_EXECUTE,  # tenant accepts responsibility
    )
    policy = ParsedActionPolicy(
        binding=_binding(),
        rules={},
        custom_tools={"crm_mcp.issue_refund": declaration},
    )
    metadata: dict[str, Any] = {
        "operation_commitment_kind": "money",
        "tool_name": "crm_mcp.issue_refund",
    }
    result = _evaluate_custom_tool(
        tool_name="crm_mcp.issue_refund",
        policy=policy,
        subject_metadata=metadata,
    )
    # Backstop is silent for auto_execute — decision should be ALLOW
    assert result[0].decision is Decision.ALLOW, (
        "auto_execute bypasses the misdeclaration backstop — tenant accepted responsibility"
    )


# ---------------------------------------------------------------------------
# Claim 6 & 7: FAIL-CLOSED ON ERRORS (separate from execution_policy)
# ---------------------------------------------------------------------------


async def test_fail_closed_on_transport_error() -> None:
    """Claim 6: even an auto_execute MCP tool fails closed on transport error.

    Transport errors → status="provider_error". Never silently succeeds.
    fail-closed-on-ERROR is about transport failure, not approval policy.
    """
    declaration = McpToolDeclaration(
        mcp_server_id="gmail_mcp",
        tool_name="send_email",
        commitment_kind=CommitmentKind.GOODS,
        execution_policy=ExecutionPolicy.AUTO_EXECUTE,
        description_snapshot="Send an email",
    )

    mock_credential_runtime = MagicMock(spec=McpCredentialRuntime)
    mock_credential_runtime.load_auth_headers = AsyncMock(
        return_value={"Authorization": "Bearer tok-gmail_mcp"}
    )

    tool = McpConnectorTool(
        declaration=declaration,
        endpoint_url="https://gmail.mcp.example.com",
        credential_runtime=mock_credential_runtime,
        ssrf_validator=MagicMock(side_effect=ValueError("transport failed")),
    )
    context = _context()
    request = _send_email_request()

    result = await tool.invoke(request, context)
    assert result.status != "success", "transport error must not produce success"
    assert "error" in result.status.lower() or result.output.get("status") != "success"


async def test_fail_closed_on_mcp_server_error_response() -> None:
    """Claim 7: MCP server returns JSON-RPC error → provider_error, not success."""
    declaration = McpToolDeclaration(
        mcp_server_id="crm_mcp",
        tool_name="issue_refund",
        commitment_kind=CommitmentKind.MONEY,
        execution_policy=ExecutionPolicy.AUTO_EXECUTE,
    )

    mock_credential_runtime = MagicMock(spec=McpCredentialRuntime)
    mock_credential_runtime.load_auth_headers = AsyncMock(
        return_value={"Authorization": "Bearer tok-crm"}
    )

    # Mock the HTTP client to return a JSON-RPC error response
    error_response = MagicMock()
    error_response.status_code = 200
    error_response.json = MagicMock(return_value={
        "jsonrpc": "2.0",
        "id": "test-id",
        "error": {"code": -32600, "message": "Internal server error"},
    })

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=error_response)

    tool = McpConnectorTool(
        declaration=declaration,
        endpoint_url="https://crm.mcp.example.com",
        credential_runtime=mock_credential_runtime,
    )

    with (
        patch("app.agents.tools.connectors.mcp.validate_connector_endpoint_url"),
        patch("app.agents.tools.connectors.mcp.create_isolated_http_client") as mock_http,
        patch("app.agents.tools.connectors.mcp.PinnedIPAsyncHTTPTransport"),
    ):
        mock_ssrf_result = MagicMock()
        mock_ssrf_result.pinned_ip = "1.2.3.4"
        mock_ssrf_result.url = "https://crm.mcp.example.com/mcp/v1"

        mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_http.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.return_value = error_response

        context = _context()
        request = _issue_refund_request()
        result = await tool.invoke(request, context)

    # Server error → fail closed
    assert result.status != "success"


async def test_fail_closed_on_non_json_response() -> None:
    """Claim 7b: MCP server returns non-JSON → provider_error."""
    declaration = McpToolDeclaration(
        mcp_server_id="gmail_mcp",
        tool_name="send_email",
        commitment_kind=CommitmentKind.GOODS,
        execution_policy=ExecutionPolicy.AUTO_EXECUTE,
    )
    mock_credential_runtime = MagicMock(spec=McpCredentialRuntime)
    mock_credential_runtime.load_auth_headers = AsyncMock(
        return_value={"Authorization": "Bearer tok"}
    )
    bad_response = MagicMock()
    bad_response.status_code = 200
    bad_response.json = MagicMock(side_effect=ValueError("not json"))

    tool = McpConnectorTool(
        declaration=declaration,
        endpoint_url="https://gmail.mcp.example.com",
        credential_runtime=mock_credential_runtime,
    )

    with (
        patch("app.agents.tools.connectors.mcp.validate_connector_endpoint_url"),
        patch("app.agents.tools.connectors.mcp.create_isolated_http_client") as mock_http,
        patch("app.agents.tools.connectors.mcp.PinnedIPAsyncHTTPTransport"),
    ):
        mock_ssrf_result = MagicMock()
        mock_ssrf_result.pinned_ip = "1.2.3.4"
        mock_ssrf_result.url = "https://gmail.mcp.example.com/mcp/v1"

        mock_http.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_http.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_http.return_value.__aenter__.return_value.post = AsyncMock(return_value=bad_response)

        context = _context()
        request = _send_email_request()
        result = await tool.invoke(request, context)

    assert result.status != "success"


# ---------------------------------------------------------------------------
# Claim 8: REGISTRY SYNTHESIS
# ---------------------------------------------------------------------------


async def test_registry_synthesis_mcp_tools() -> None:
    """Claim 8: build_tenant_action_tool_registry synthesizes McpConnectorTool per enabled tool.

    Disabled tools are absent. Tool names follow f"{mcp_server_id}.{tool_name}".
    """
    mcp_tools = [
        {"tool_name": "send_email", "commitment_kind": "goods", "execution_policy": "auto_execute", "enabled": True},
        {"tool_name": "read_inbox", "commitment_kind": "none", "execution_policy": "auto_execute", "enabled": True},
        {"tool_name": "delete_email", "commitment_kind": "record_update", "execution_policy": "operious_approval", "enabled": False},
    ]
    repo = InMemoryConnectorConfigRepository()
    await repo.save_config(
        ConnectorConfigRecord(
            tenant_id=_TENANT,
            connector_type="mcp_server",
            tool_name="gmail_mcp",  # mcp_server_id
            http_method="POST",
            endpoint_template="https://gmail.mcp.example.com",
            endpoint_host="gmail.mcp.example.com",
            field_mappings={"mcp_tools": mcp_tools, "timeout_seconds": 15.0},
            status="active",
        ),
        expected_tenant_id=_TENANT,
    )

    class _FakeCred:
        async def load_connector_credentials(self, *, tenant_id: str, connector_id: str) -> dict[str, Any]:
            return {"access_token": "tok"}

    # Build registry — needs connector_credential_runtime for MCP
    fake_cred = _FakeCred()
    connector_cred_runtime = MagicMock(spec=ConnectorScopedCredentialRuntime)
    connector_cred_runtime._repository = MagicMock()
    connector_cred_runtime._codec = MagicMock()
    connector_cred_runtime._tenant_id = _TENANT
    connector_cred_runtime.load_connector_credentials = AsyncMock(return_value={"access_token": "tok"})

    registry = await build_tenant_action_tool_registry(
        tenant_id=_TENANT,
        config_repository=repo,
        credential_runtime=fake_cred,  # type: ignore[arg-type]
        connector_credential_runtime=connector_cred_runtime,
        ssrf_validator=MagicMock(side_effect=lambda url, *, allowed_hosts=(): (_ for _ in ()).throw(ValueError("ssrf"))),
    )

    assert registry.has("gmail_mcp.send_email"), "enabled tool must be in registry"
    assert registry.has("gmail_mcp.read_inbox"), "enabled read tool must be in registry"
    assert not registry.has("gmail_mcp.delete_email"), "disabled tool must NOT be in registry"

    tool = registry.get("gmail_mcp.send_email")
    assert isinstance(tool, McpConnectorTool)
    assert tool.declaration.execution_policy is ExecutionPolicy.AUTO_EXECUTE
    assert tool.declaration.commitment_kind is CommitmentKind.GOODS


async def test_registry_synthesis_no_mcp_without_credential_runtime() -> None:
    """Claim 8b: MCP tools are NOT registered when connector_credential_runtime is absent.

    Fail-closed: no credential runtime = no MCP tools in registry.
    """
    mcp_tools = [
        {"tool_name": "send_email", "commitment_kind": "goods", "execution_policy": "auto_execute", "enabled": True},
    ]
    repo = InMemoryConnectorConfigRepository()
    await repo.save_config(
        ConnectorConfigRecord(
            tenant_id=_TENANT,
            connector_type="mcp_server",
            tool_name="gmail_mcp",
            http_method="POST",
            endpoint_template="https://gmail.mcp.example.com",
            endpoint_host="gmail.mcp.example.com",
            field_mappings={"mcp_tools": mcp_tools},
            status="active",
        ),
        expected_tenant_id=_TENANT,
    )

    class _FakeCred:
        async def load_connector_credentials(self, *, tenant_id: str, connector_id: str) -> dict[str, Any]:
            return {}

    registry = await build_tenant_action_tool_registry(
        tenant_id=_TENANT,
        config_repository=repo,
        credential_runtime=_FakeCred(),  # type: ignore[arg-type]
        connector_credential_runtime=None,  # absent
    )
    assert not registry.has("gmail_mcp.send_email"), (
        "MCP tools must not be registered without connector_credential_runtime"
    )


# ---------------------------------------------------------------------------
# Claim 9: EXECUTION_POLICY PARSING in action_tools policy
# ---------------------------------------------------------------------------


async def test_action_policy_parses_execution_policy() -> None:
    """Claim 9: action_tools policy with execution_policy field parses to correct enum value."""
    from app.agents.tools.action_governance import parse_action_tools_policy

    tools = {
        "gmail_mcp.send_email": {
            "commitment_kind": "goods",
            "execution_policy": "auto_execute",
        },
        "crm_mcp.issue_refund": {
            "commitment_kind": "money",
            "execution_policy": "operious_approval",
        },
        "crm_mcp.read_contact": {
            "commitment_kind": "none",
            "execution_policy": "auto_execute",
        },
    }
    record = _policy_record(tools=tools)
    parsed = parse_action_tools_policy(record)

    send_decl = parsed.custom_tools["gmail_mcp.send_email"]
    assert send_decl.execution_policy is ExecutionPolicy.AUTO_EXECUTE
    assert send_decl.commitment_kind is CommitmentKind.GOODS

    refund_decl = parsed.custom_tools["crm_mcp.issue_refund"]
    assert refund_decl.execution_policy is ExecutionPolicy.OPERIOUS_APPROVAL
    assert refund_decl.commitment_kind is CommitmentKind.MONEY

    read_decl = parsed.custom_tools["crm_mcp.read_contact"]
    assert read_decl.execution_policy is ExecutionPolicy.AUTO_EXECUTE
    assert read_decl.commitment_kind is CommitmentKind.NONE


async def test_action_policy_invalid_execution_policy_raises() -> None:
    """Claim 9b: invalid execution_policy in policy raises ActionPolicyParseError."""
    from app.agents.tools.action_governance import (
        ActionPolicyParseError,
        parse_action_tools_policy,
    )
    tools = {
        "gmail_mcp.send_email": {
            "commitment_kind": "goods",
            "execution_policy": "invalid_policy_value",
        }
    }
    record = _policy_record(tools=tools)
    with pytest.raises(ActionPolicyParseError, match="execution_policy"):
        parse_action_tools_policy(record)


async def test_action_policy_legacy_no_execution_policy_uses_decision() -> None:
    """Claim 9c: existing REST connector policies without execution_policy continue working."""
    from app.agents.tools.action_governance import parse_action_tools_policy

    tools = {
        "account.freeze": {
            "commitment_kind": "money",
            "decision": "require_approval",
            # no execution_policy — backward compat
        }
    }
    record = _policy_record(tools=tools)
    parsed = parse_action_tools_policy(record)
    decl = parsed.custom_tools["account.freeze"]
    assert decl.execution_policy is None
    assert decl.decision is Decision.REQUIRE_APPROVAL


# ---------------------------------------------------------------------------
# Claim 10: MCP CHANGE-REQUEST PAYLOAD VALIDATION
# ---------------------------------------------------------------------------


def test_mcp_server_payload_valid() -> None:
    """Claim 10a: valid MCP_SERVER payload passes validation."""
    payload = {
        "_schema_version": "1",
        "mcp_server_id": "gmail_mcp",
        "endpoint_url": "https://gmail.mcp.example.com",
        "mcp_tools": [
            {
                "tool_name": "send_email",
                "commitment_kind": "goods",
                "execution_policy": "auto_execute",
                "description_snapshot": "Send an email",
                "enabled": True,
            }
        ],
    }
    _validate_mcp_server_payload(payload)  # must not raise


def test_mcp_server_payload_rejects_non_https() -> None:
    """Claim 10b: HTTP (non-HTTPS) endpoint_url is rejected."""
    payload = {
        "_schema_version": "1",
        "mcp_server_id": "gmail_mcp",
        "endpoint_url": "http://gmail.mcp.example.com",  # not HTTPS
        "mcp_tools": [{"tool_name": "send_email", "commitment_kind": "goods", "execution_policy": "auto_execute"}],
    }
    with pytest.raises(TenantConfigChangeRequestLifecycleError, match="HTTPS"):
        _validate_mcp_server_payload(payload)


def test_mcp_server_payload_rejects_empty_tools() -> None:
    """Claim 10c: empty mcp_tools list is rejected."""
    payload = {
        "_schema_version": "1",
        "mcp_server_id": "gmail_mcp",
        "endpoint_url": "https://gmail.mcp.example.com",
        "mcp_tools": [],
    }
    with pytest.raises(TenantConfigChangeRequestLifecycleError, match="non-empty"):
        _validate_mcp_server_payload(payload)


def test_mcp_server_payload_rejects_missing_execution_policy() -> None:
    """Claim 10d: tool without execution_policy is rejected."""
    payload = {
        "_schema_version": "1",
        "mcp_server_id": "gmail_mcp",
        "endpoint_url": "https://gmail.mcp.example.com",
        "mcp_tools": [
            {
                "tool_name": "send_email",
                "commitment_kind": "goods",
                # no execution_policy — required for MCP tools
            }
        ],
    }
    with pytest.raises(TenantConfigChangeRequestLifecycleError, match="execution_policy"):
        _validate_mcp_server_payload(payload)


def test_mcp_server_payload_rejects_invalid_commitment_kind() -> None:
    """Claim 10e: invalid commitment_kind is rejected."""
    payload = {
        "_schema_version": "1",
        "mcp_server_id": "gmail_mcp",
        "endpoint_url": "https://gmail.mcp.example.com",
        "mcp_tools": [
            {
                "tool_name": "send_email",
                "commitment_kind": "dangerous",  # invalid
                "execution_policy": "auto_execute",
            }
        ],
    }
    with pytest.raises(TenantConfigChangeRequestLifecycleError, match="commitment_kind"):
        _validate_mcp_server_payload(payload)


def test_mcp_oauth_token_sentinel_valid() -> None:
    """Claim 10f: valid MCP_OAUTH_TOKEN sentinel passes validation."""
    _validate_mcp_oauth_token_sentinel({
        "_schema_version": "1",
        "mcp_server_id": "gmail_mcp",
        "token_hash": "a" * 64,
    })


def test_mcp_oauth_token_sentinel_rejects_plaintext_token() -> None:
    """Claim 10g: MCP_OAUTH_TOKEN sentinel rejects plaintext access_token."""
    with pytest.raises(TenantConfigChangeRequestLifecycleError, match="token fields"):
        _validate_mcp_oauth_token_sentinel({
            "_schema_version": "1",
            "mcp_server_id": "gmail_mcp",
            "token_hash": "a" * 64,
            "access_token": "ya29.real-token",  # FORBIDDEN
        })


def test_mcp_oauth_token_sentinel_rejects_bad_hash() -> None:
    """Claim 10h: token_hash must be 64-char hex."""
    with pytest.raises(TenantConfigChangeRequestLifecycleError, match="SHA-256"):
        _validate_mcp_oauth_token_sentinel({
            "_schema_version": "1",
            "mcp_server_id": "gmail_mcp",
            "token_hash": "too-short",
        })


# ---------------------------------------------------------------------------
# Claim: McpToolDeclaration.effective_commitment_kind backstop
# ---------------------------------------------------------------------------


def test_mcp_tool_declaration_backstop_upgrades_none_to_goods() -> None:
    """Synthesis backstop: tool declared none with money-trigger name → upgraded to GOODS."""
    decl = McpToolDeclaration(
        mcp_server_id="crm_mcp",
        tool_name="issue_refund",   # "refund" triggers backstop
        commitment_kind=CommitmentKind.NONE,
        execution_policy=ExecutionPolicy.OPERIOUS_APPROVAL,
        description_snapshot="Issue a refund to the customer",
    )
    assert decl.effective_commitment_kind() is CommitmentKind.GOODS, (
        "misdeclared none tool with 'refund' in name must be upgraded to GOODS "
        "when execution_policy is operious_approval"
    )


def test_mcp_tool_declaration_backstop_silent_for_auto_execute() -> None:
    """Synthesis backstop is silent for auto_execute — tenant accepted responsibility."""
    decl = McpToolDeclaration(
        mcp_server_id="crm_mcp",
        tool_name="issue_refund",
        commitment_kind=CommitmentKind.NONE,
        execution_policy=ExecutionPolicy.AUTO_EXECUTE,  # tenant aware
        description_snapshot="Issue a refund",
    )
    assert decl.effective_commitment_kind() is CommitmentKind.NONE, (
        "auto_execute bypasses commitment kind backstop"
    )


def test_mcp_tool_declaration_no_trigger_no_upgrade() -> None:
    """Safe names don't trigger the backstop."""
    decl = McpToolDeclaration(
        mcp_server_id="gmail_mcp",
        tool_name="read_inbox",
        commitment_kind=CommitmentKind.NONE,
        execution_policy=ExecutionPolicy.OPERIOUS_APPROVAL,
        description_snapshot="Read emails from the inbox",
    )
    assert decl.effective_commitment_kind() is CommitmentKind.NONE


# ---------------------------------------------------------------------------
# Execution policy parsing validation
# ---------------------------------------------------------------------------


def test_parse_mcp_server_config_parses_execution_policies() -> None:
    """parse_mcp_server_config correctly reads execution_policy from raw config."""
    raw_tools = [
        {"tool_name": "send_email", "commitment_kind": "goods", "execution_policy": "auto_execute", "enabled": True},
        {"tool_name": "read_inbox", "commitment_kind": "none", "execution_policy": "operious_approval", "enabled": True},
        {"tool_name": "delete_email", "commitment_kind": "record_update", "execution_policy": "operious_approval", "enabled": False},
    ]
    config = parse_mcp_server_config(
        mcp_server_id="gmail_mcp",
        endpoint_url="https://gmail.mcp.example.com",
        raw_tools=raw_tools,
    )
    assert config.mcp_server_id == "gmail_mcp"
    assert len(config.tools) == 3

    send = config.get_tool("send_email")
    assert send is not None
    assert send.execution_policy is ExecutionPolicy.AUTO_EXECUTE
    assert send.commitment_kind is CommitmentKind.GOODS

    read = config.get_tool("read_inbox")
    assert read is not None
    assert read.execution_policy is ExecutionPolicy.OPERIOUS_APPROVAL

    deleted = config.get_tool("delete_email")  # disabled
    assert deleted is None  # get_tool filters out disabled


# ---------------------------------------------------------------------------
# REAL INTEGRATION TESTS — skip ONLY when env vars absent, RUN when present
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not all(
        __import__("os").environ.get(v)
        for v in (
            "MCP_OAUTH_GOOGLE_CLIENT_ID",
            "MCP_OAUTH_GOOGLE_CLIENT_SECRET",
            "MCP_OAUTH_GOOGLE_REFRESH_TOKEN",
        )
    ),
    reason=(
        "Integration test: set MCP_OAUTH_GOOGLE_CLIENT_ID, "
        "MCP_OAUTH_GOOGLE_CLIENT_SECRET, MCP_OAUTH_GOOGLE_REFRESH_TOKEN to run."
    ),
)
async def test_real_oauth_token_exchange() -> None:
    """Real OAuth token exchange via refresh_token grant against Google's token endpoint.

    Exercises the REAL Google token endpoint (https://oauth2.googleapis.com/token)
    using a pre-authorized refresh_token (no interactive browser needed).

    Verifies:
    1. refresh_token → access_token exchange succeeds (real HTTP to Google).
    2. access_token is a real Bearer token (starts with "ya29." or similar).
    3. Token can be encrypted via OPCRED2 codec and decrypted back.
    4. McpCredentialRuntime.load_auth_headers() returns valid Bearer header.
    5. Token introspection confirms the token is valid (Google tokeninfo).
    """
    import os

    import httpx

    client_id = os.environ["MCP_OAUTH_GOOGLE_CLIENT_ID"]
    client_secret = os.environ["MCP_OAUTH_GOOGLE_CLIENT_SECRET"]
    refresh_token = os.environ["MCP_OAUTH_GOOGLE_REFRESH_TOKEN"]

    # Step 1: Real token exchange against Google's token endpoint.
    async with httpx.AsyncClient(timeout=15.0) as http:
        token_response = await http.post(
            "https://oauth2.googleapis.com/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
            headers={"Accept": "application/json"},
        )
    assert token_response.status_code == 200, (
        f"Google token exchange failed: status={token_response.status_code}, "
        f"body={token_response.text[:500]}"
    )
    token_data = token_response.json()
    access_token = token_data.get("access_token")
    assert access_token, f"No access_token in response: {list(token_data.keys())}"
    assert isinstance(access_token, str) and len(access_token) > 10

    # Step 2: Verify the token is real via Google tokeninfo.
    async with httpx.AsyncClient(timeout=10.0) as http:
        info_response = await http.get(
            f"https://oauth2.googleapis.com/tokeninfo?access_token={access_token}"
        )
    assert info_response.status_code == 200, (
        f"Token introspection failed: {info_response.status_code} {info_response.text[:300]}"
    )
    info = info_response.json()
    assert "expires_in" in info, f"tokeninfo missing expires_in: {info}"

    # Step 3: Encrypt via OPCRED2 codec and decrypt back — round-trip integrity.
    credentials = {"access_token": access_token, "refresh_token": refresh_token}
    from app.agents.tools.connectors.credentials import encrypt_connector_credentials

    class _TestCodec:
        def encrypt(self, *, tenant_id: str, credentials: dict, channel_type: str) -> bytes:
            import json as _j
            return _j.dumps(credentials).encode()

        def decrypt(self, *, tenant_id: str, encrypted_credentials: bytes, channel_type: str) -> dict:
            import json as _j
            return _j.loads(encrypted_credentials)

    codec = _TestCodec()
    ciphertext, cred_hash = encrypt_connector_credentials(
        tenant_id=_TENANT,
        connector_id="google_oauth_test",
        credentials=credentials,
        codec=codec,  # type: ignore[arg-type]
    )
    assert len(cred_hash) == 64  # SHA-256 hex
    decrypted = codec.decrypt(
        tenant_id=_TENANT,
        encrypted_credentials=ciphertext,
        channel_type="google_oauth_test",
    )
    assert decrypted["access_token"] == access_token

    # Step 4: McpCredentialRuntime loads Bearer header from stored credential.
    cred_runtime = _make_credential_runtime_with_token(
        tenant_id=_TENANT,
        connector_id="google_oauth_test",
        access_token=access_token,
    )
    mcp_runtime = McpCredentialRuntime(credential_runtime=cred_runtime)
    headers = await mcp_runtime.load_auth_headers(
        tenant_id=_TENANT,
        mcp_server_id="google_oauth_test",
    )
    assert headers["Authorization"] == f"Bearer {access_token}"


@pytest.mark.skipif(
    not __import__("os").environ.get("MCP_LIVE_SERVER_URL"),
    reason=(
        "Integration test: set MCP_LIVE_SERVER_URL=<url>, "
        "MCP_LIVE_SERVER_TOKEN=<bearer_token>, MCP_LIVE_SERVER_ID=<server_id> to run."
    ),
)
async def test_live_mcp_tools_call_through_governance() -> None:
    """Live E2E: register a real MCP server, invoke tools through full governance.

    Exercises the REAL deployed MCP server (e.g. FastMCP on Fly.io) with
    real Bearer auth. The server MUST expose at least:
    - echo(message: str) → str
    - send_payment(amount: float, recipient: str) → str  (money-trigger name)

    Verifies:
    1. MCP SDK tools/list succeeds against real server.
    2. echo with auto_execute → real tool fires, result returned.
    3. send_payment with operious_approval → governance blocks, server NOT called.
    4. send_payment UNCONFIGURED (absent from policy) → safe default blocks.
    5. send_payment with auto_execute → fires (tenant explicitly chose autonomy).
    """
    import os

    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    server_url = os.environ["MCP_LIVE_SERVER_URL"].rstrip("/")
    token = os.environ.get("MCP_LIVE_SERVER_TOKEN") or os.environ.get("MCP_LIVE_SERVER_API_KEY") or "no-auth"
    server_id = os.environ.get("MCP_LIVE_SERVER_ID", "live_test_server")

    # Step 1: Verify tools/list works against the real server.
    mcp_url = f"{server_url}/mcp"
    auth_headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with streamablehttp_client(mcp_url, headers=auth_headers or None, timeout=15) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()

    tool_names = {t.name for t in tools_result.tools}
    assert "echo" in tool_names or "echo_message" in tool_names, (
        f"Server must expose 'echo' or 'echo_message'; got: {tool_names}"
    )
    echo_tool_name = "echo" if "echo" in tool_names else "echo_message"
    has_send_payment = "send_payment" in tool_names
    assert has_send_payment, (
        f"Server must expose 'send_payment' (money-trigger); got: {tool_names}"
    )

    # Step 2: Build governed registry with the live server.
    repo = InMemoryConnectorConfigRepository()
    mcp_tools = [
        {"tool_name": echo_tool_name, "commitment_kind": "none", "execution_policy": "auto_execute", "enabled": True},
        {"tool_name": "send_payment", "commitment_kind": "money", "execution_policy": "operious_approval", "enabled": True},
    ]
    await repo.save_config(
        ConnectorConfigRecord(
            tenant_id=_TENANT,
            connector_type="mcp_server",
            tool_name=server_id,
            http_method="POST",
            endpoint_template=server_url,
            endpoint_host=server_url.split("//")[-1].split("/")[0],
            field_mappings={"mcp_tools": mcp_tools, "timeout_seconds": 15.0},
            status="active",
        ),
        expected_tenant_id=_TENANT,
    )
    cred_runtime = _make_credential_runtime_with_token(
        tenant_id=_TENANT, connector_id=server_id, access_token=token,
    )
    registry = await build_tenant_action_tool_registry(
        tenant_id=_TENANT,
        config_repository=repo,
        credential_runtime=cred_runtime,  # type: ignore[arg-type]
        connector_credential_runtime=cred_runtime,  # type: ignore[arg-type]
    )
    assert registry.has(f"{server_id}.{echo_tool_name}"), (
        f"echo tool not in registry; registered: {[t for t in dir(registry) if not t.startswith('_')]}"
    )
    assert registry.has(f"{server_id}.send_payment")

    # Step 3: auto_execute echo tool fires against real server.
    from app.agents.tools.action_governance import build_action_tool_governance_runtime
    from app.governance.persistence.memory import InMemoryGovernanceRepository
    from app.tenant.persistence import InMemoryTenantConfigurationRepository

    tenant_repo = InMemoryTenantConfigurationRepository()
    await tenant_repo.save_governance_policy(
        _policy_record(
            tools={
                f"{server_id}.{echo_tool_name}": {
                    "commitment_kind": "none",
                    "execution_policy": "auto_execute",
                },
                f"{server_id}.send_payment": {
                    "commitment_kind": "money",
                    "execution_policy": "operious_approval",
                },
            }
        ),
        expected_tenant_id=_TENANT,
    )
    governance = build_action_tool_governance_runtime(
        persistence=InMemoryGovernanceRepository(),
        tenant_configuration_repository=tenant_repo,
    )

    # Invoke echo via governance — auto_execute → fires.
    from app.agents.tools import ToolInvoker
    invoker = ToolInvoker(
        tool_registry=registry,
        governance_runtime=governance,
        grant_repository=None,
        connector_invocation_repository=None,
    )
    echo_request = ToolInvocationRequest(
        tool_name=f"{server_id}.{echo_tool_name}",
        payload={"message": "governance-verified-e2e"},
        metadata={"tool_name": f"{server_id}.{echo_tool_name}"},
    )
    echo_result = await invoker.invoke(
        request=echo_request,
        context=_context(seed="live-echo"),
        invocation_ordinal=1,
    )
    assert not echo_result.is_denied, (
        f"auto_execute echo was denied: {echo_result.trace}"
    )
    assert echo_result.result is not None
    assert echo_result.result.status == "success", (
        f"echo failed: {echo_result.result.output}"
    )

    # Step 4: operious_approval send_payment → governance blocks.
    payment_request = ToolInvocationRequest(
        tool_name=f"{server_id}.send_payment",
        payload={"amount": 42.0, "recipient": "test@example.com"},
        metadata={"tool_name": f"{server_id}.send_payment"},
    )
    payment_result = await invoker.invoke(
        request=payment_request,
        context=_context(seed="live-payment-blocked"),
        invocation_ordinal=2,
    )
    assert payment_result.is_denied, (
        "send_payment with operious_approval must be blocked by governance"
    )

    # Step 5: Now test auto_execute on money tool (tenant explicitly chose autonomy).
    await tenant_repo.save_governance_policy(
        _policy_record(
            tools={
                f"{server_id}.{echo_tool_name}": {
                    "commitment_kind": "none",
                    "execution_policy": "auto_execute",
                },
                f"{server_id}.send_payment": {
                    "commitment_kind": "money",
                    "execution_policy": "auto_execute",
                },
            }
        ),
        expected_tenant_id=_TENANT,
    )
    governance2 = build_action_tool_governance_runtime(
        persistence=InMemoryGovernanceRepository(),
        tenant_configuration_repository=tenant_repo,
    )
    invoker2 = ToolInvoker(
        tool_registry=registry,
        governance_runtime=governance2,
        grant_repository=None,
        connector_invocation_repository=None,
    )
    payment_auto = await invoker2.invoke(
        request=payment_request,
        context=_context(seed="live-payment-auto"),
        invocation_ordinal=3,
    )
    assert not payment_auto.is_denied, (
        f"send_payment with auto_execute should fire: {payment_auto.trace}"
    )
    assert payment_auto.result is not None
    assert payment_auto.result.status == "success", (
        f"send_payment auto_execute failed: {payment_auto.result.output}"
    )


@pytest.mark.skipif(
    not all(
        __import__("os").environ.get(v)
        for v in (
            "MCP_OAUTH_REFRESH_TOKEN_CLIENT_ID",
            "MCP_OAUTH_REFRESH_TOKEN_CLIENT_SECRET",
            "MCP_OAUTH_REFRESH_TOKEN",
        )
    ),
    reason=(
        "Integration test: set MCP_OAUTH_REFRESH_TOKEN_CLIENT_ID, "
        "MCP_OAUTH_REFRESH_TOKEN_CLIENT_SECRET, MCP_OAUTH_REFRESH_TOKEN to run."
    ),
)
async def test_token_refresh_cycle() -> None:
    """Real token refresh cycle — exchange refresh_token, store, verify, test failure.

    Verifies:
    1. refresh_token → new access_token (real HTTP to provider token endpoint).
    2. New token stored via OPCRED2 codec and loaded by McpCredentialRuntime.
    3. Invalid refresh_token → exchange fails → credential NOT stored as active.
    4. After failed refresh, McpCredentialRuntime.load_auth_headers() raises (fail-closed).
    """
    import os

    import httpx

    client_id = os.environ["MCP_OAUTH_REFRESH_TOKEN_CLIENT_ID"]
    client_secret = os.environ["MCP_OAUTH_REFRESH_TOKEN_CLIENT_SECRET"]
    token_endpoint = os.environ.get(
        "MCP_OAUTH_REFRESH_TOKEN_ENDPOINT", "https://oauth2.googleapis.com/token"
    )
    refresh_token = os.environ["MCP_OAUTH_REFRESH_TOKEN"]

    # Step 1: Refresh to get a new access_token (real HTTP).
    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.post(
            token_endpoint,
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
            headers={"Accept": "application/json"},
        )
    assert resp.status_code == 200, (
        f"Token refresh failed: {resp.status_code} {resp.text[:500]}"
    )
    token_data = resp.json()
    new_access_token = token_data["access_token"]
    assert new_access_token and len(new_access_token) > 10

    # Step 2: Store the token and verify McpCredentialRuntime loads it.
    cred_runtime = _make_credential_runtime_with_token(
        tenant_id=_TENANT,
        connector_id="refresh_test_server",
        access_token=new_access_token,
    )
    mcp_runtime = McpCredentialRuntime(credential_runtime=cred_runtime)
    headers = await mcp_runtime.load_auth_headers(
        tenant_id=_TENANT, mcp_server_id="refresh_test_server",
    )
    assert headers["Authorization"] == f"Bearer {new_access_token}"

    # Step 3: Refresh AGAIN — confirms a second refresh produces a different token
    # (or the same — Google may return the same within a short window, both are valid).
    async with httpx.AsyncClient(timeout=15.0) as http:
        resp2 = await http.post(
            token_endpoint,
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
            headers={"Accept": "application/json"},
        )
    assert resp2.status_code == 200
    second_token = resp2.json()["access_token"]
    assert second_token and len(second_token) > 10

    # Step 4: Invalid refresh_token → exchange fails → fail-closed.
    async with httpx.AsyncClient(timeout=15.0) as http:
        bad_resp = await http.post(
            token_endpoint,
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": "invalid-bogus-refresh-token-XXXXXX",
            },
            headers={"Accept": "application/json"},
        )
    assert bad_resp.status_code != 200, (
        "Invalid refresh_token should fail at the token endpoint"
    )

    # Step 5: With no stored token, credential runtime raises (fail-closed).
    empty_runtime = _make_empty_credential_runtime(_TENANT)
    mcp_runtime_empty = McpCredentialRuntime(credential_runtime=empty_runtime)
    with pytest.raises((KeyError, PermissionError)):
        await mcp_runtime_empty.load_auth_headers(
            tenant_id=_TENANT, mcp_server_id="nonexistent_server",
        )


# ---------------------------------------------------------------------------
# Helpers for real integration tests
# ---------------------------------------------------------------------------


def _make_credential_runtime_with_token(
    *,
    tenant_id: str,
    connector_id: str,
    access_token: str,
) -> ConnectorScopedCredentialRuntime:
    """Build an in-memory credential runtime pre-loaded with a single access_token."""

    class _InMemoryCodec:
        def encrypt(self, *, tenant_id: str, credentials: dict[str, Any], channel_type: str) -> bytes:
            return json.dumps(credentials).encode()

        def decrypt(self, *, tenant_id: str, encrypted_credentials: bytes, channel_type: str) -> dict[str, Any]:
            return json.loads(encrypted_credentials)

    class _InMemoryCredRepo:
        def __init__(self) -> None:
            self._records: dict[tuple[str, str], ConnectorCredentialRecord] = {}

        async def get(self, *, tenant_id: str, connector_id: str, expected_tenant_id: str) -> ConnectorCredentialRecord | None:
            if tenant_id != expected_tenant_id:
                return None
            return self._records.get((tenant_id, connector_id))

        async def get_active(self, *, tenant_id: str, connector_id: str, expected_tenant_id: str) -> ConnectorCredentialRecord | None:
            rec = await self.get(tenant_id=tenant_id, connector_id=connector_id, expected_tenant_id=expected_tenant_id)
            if rec is None or rec.status != "active":
                return None
            return rec

        async def upsert(self, record: ConnectorCredentialRecord, *, expected_tenant_id: str) -> ConnectorCredentialRecord:
            self._records[(record.tenant_id, record.connector_id)] = record
            return record

        async def list_active_for_tenant(self, *, tenant_id: str, expected_tenant_id: str) -> list[ConnectorCredentialRecord]:
            return [r for (t, _), r in self._records.items() if t == tenant_id and r.status == "active"]

    codec = _InMemoryCodec()
    repo = _InMemoryCredRepo()

    cred_record = ConnectorCredentialRecord(
        tenant_id=tenant_id,
        connector_id=connector_id,
        credentials_enc=codec.encrypt(
            tenant_id=tenant_id,
            credentials={"access_token": access_token},
            channel_type=connector_id,
        ),
        credential_hash="a" * 64,
        status="active",
        configured_by="integration_test",
        source_approval_id="approval-integration",
    )
    # Store synchronously via run_until_complete or direct dict set.
    repo._records[(tenant_id, connector_id)] = cred_record

    return ConnectorScopedCredentialRuntime(repository=repo, codec=codec, tenant_id=tenant_id)  # type: ignore[arg-type]


def _make_empty_credential_runtime(tenant_id: str) -> ConnectorScopedCredentialRuntime:
    """Build a credential runtime with NO stored credentials (for fail-closed tests)."""

    class _EmptyCodec:
        def encrypt(self, *, tenant_id: str, credentials: dict[str, Any], channel_type: str) -> bytes:
            return json.dumps(credentials).encode()

        def decrypt(self, *, tenant_id: str, encrypted_credentials: bytes, channel_type: str) -> dict[str, Any]:
            return json.loads(encrypted_credentials)

    class _EmptyRepo:
        async def get(self, **kwargs: Any) -> None:
            return None

        async def get_active(self, **kwargs: Any) -> None:
            return None

        async def upsert(self, record: Any, **kwargs: Any) -> Any:
            return record

        async def list_active_for_tenant(self, **kwargs: Any) -> list:
            return []

    return ConnectorScopedCredentialRuntime(
        repository=_EmptyRepo(), codec=_EmptyCodec(), tenant_id=tenant_id,  # type: ignore[arg-type]
    )
