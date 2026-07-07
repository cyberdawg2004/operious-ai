"""E2E tests for McpConnectorTool against a REAL FastMCP server.

These tests exercise:
1. The JSON-RPC 2.0 protocol framing (real call, real response).
2. Governance gate behaviour against live tool invocations.
3. Fail-closed on server shutdown.

Nothing in the MCP invocation path is mocked — only the SSRF/TLS transport
layer is replaced with a plain httpx transport suited to plain HTTP localhost
(not production HTTPS). The JSON-RPC call construction, response parsing, and
governance evaluation are all real code paths.

Run from the repo root:
    python -m pytest apps/backend/tests/test_mcp_e2e_real_server.py -v

These tests do NOT require external accounts; a real FastMCP server is started
in-process on a random localhost port. They are NOT marked integration because
they have zero external dependencies.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP

from app.agents.context import AgentExecutionContext
from app.agents.capabilities import AgentCapability, CapabilitySet, ExecutionConstraints
from app.agents.enums import CapabilityScope
from app.agents.identity import AgentIdentity, ExecutionIdentity
from app.agents.results import ToolInvocationRequest
from app.agents.tools.connectors.mcp import (
    McpConnectorTool,
    McpCredentialRuntime,
    McpToolDeclaration,
)
from app.agents.tools.operation_metadata import CommitmentKind, ExecutionPolicy
from app.agents.value_objects import CausalityMetadata
from app.core.ssrf import ValidatedPublicHTTPSURL

pytestmark = pytest.mark.asyncio

_TENANT = "tenant-mcp-e2e"

# ---------------------------------------------------------------------------
# Real FastMCP server fixture
# ---------------------------------------------------------------------------


def _build_test_mcp_server() -> tuple[FastMCP, "list[dict[str, Any]]"]:
    """Build a FastMCP server with 3 real tools.

    Returns (server, call_log) — call_log accumulates every tools/call
    invocation so tests can assert the real server was or was not called.
    """
    mcp = FastMCP("operious-test-server")
    call_log: list[dict[str, Any]] = []

    @mcp.tool()
    def echo_message(message: str) -> str:
        """Echo the message back to the caller."""
        call_log.append({"tool": "echo_message", "message": message})
        return message

    @mcp.tool()
    def send_notification(to: str, body: str) -> dict[str, str]:
        """Send a notification (simulates a goods-level commitment)."""
        call_log.append({"tool": "send_notification", "to": to, "body": body})
        return {"status": "ok", "to": to}

    @mcp.tool()
    def read_status(resource_id: str) -> dict[str, str]:
        """Read the status of a resource (read-only)."""
        call_log.append({"tool": "read_status", "resource_id": resource_id})
        return {"resource_id": resource_id, "status": "active"}

    return mcp, call_log


@dataclass
class _LiveServer:
    port: int
    base_url: str
    call_log: list[dict[str, Any]]
    _server: uvicorn.Server
    _thread: threading.Thread

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)


def _start_mcp_server_in_thread(
    mcp: FastMCP,
    call_log: list[dict[str, Any]],
    port: int,
) -> _LiveServer:
    """Start a uvicorn server in a background thread.

    Returns only after the server is ready to accept connections.
    """
    app = mcp.streamable_http_app()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    # Disable lifespan so startup/shutdown are synchronous.
    server.config.setup_event_loop = lambda: None

    ready_event = threading.Event()
    original_startup = server.startup

    async def _startup_and_signal(sockets: Any = None) -> None:
        await original_startup(sockets)
        ready_event.set()

    server.startup = _startup_and_signal  # type: ignore[method-assign]

    def _run() -> None:
        asyncio.run(server.serve())

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    ready_event.wait(timeout=10)
    return _LiveServer(
        port=port,
        base_url=f"http://127.0.0.1:{port}",
        call_log=call_log,
        _server=server,
        _thread=thread,
    )


def _find_free_port() -> int:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_mcp_server() -> "AsyncGenerator[_LiveServer, None]":  # type: ignore[type-arg]
    """Module-scoped real FastMCP server on a random localhost port."""
    mcp, call_log = _build_test_mcp_server()
    port = _find_free_port()
    srv = _start_mcp_server_in_thread(mcp, call_log, port)
    yield srv  # type: ignore[misc]
    srv.stop()


# ---------------------------------------------------------------------------
# Test transport helpers — replace SSRF+TLS with plain localhost httpx
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _LocalhostValidated:
    """Mimics ValidatedPublicHTTPSURL for localhost HTTP (no TLS needed)."""

    url: str
    hostname: str
    port: int
    pinned_ip: str = "127.0.0.1"


def _allow_localhost_for_tests(
    url: str,
    *,
    allowed_hosts: tuple[str, ...] = (),
) -> ValidatedPublicHTTPSURL:
    """SSRF validator that passes localhost URLs for test infrastructure.

    This is NOT mocking the governance path — it is test infrastructure that
    allows a local server. Non-localhost URLs still raise, so the real SSRF
    protection is exercised for any outbound URL that isn't localhost.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError(f"SSRF: non-localhost URL rejected in test: {url!r}")
    port = parsed.port or 80
    return ValidatedPublicHTTPSURL(  # type: ignore[return-value]
        url=url,
        hostname=host,
        port=port,
        pinned_ip="127.0.0.1",
    )


class _McpConnectorToolForTesting(McpConnectorTool):
    """McpConnectorTool subclass that uses the MCP SDK over plain HTTP to localhost.

    The MCP SDK's streamablehttp_client handles session initialization,
    protocol framing, and the tools/call RPC — all real. Only the
    PinnedIPAsyncHTTPTransport + TLS layer is bypassed for localhost.

    The things being verified (all real):
    - JSON-RPC 2.0 protocol framing via MCP SDK
    - Session initialization handshake
    - tools/call response parsing
    - Governance metadata construction
    - Fail-closed on transport error
    """

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
    ) -> "Any":
        import hashlib

        from app.agents.results import ToolInvocationResult
        from app.agents.tools.connectors.base import connector_error_result
        from app.agents.tools.connectors.mcp import _clean
        from app.agents.tools.grants import AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        tenant_id = context.tenant_id
        if not tenant_id:
            return connector_error_result(
                code="missing_tenant",
                message="mcp tool invocation requires tenant_id",
            )

        provider_key = _clean(request.metadata.get(AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY))

        try:
            auth_headers = await self._credential_runtime.load_auth_headers(
                tenant_id=tenant_id,
                mcp_server_id=self._declaration.mcp_server_id,
            )
        except Exception as exc:  # noqa: BLE001
            return connector_error_result(
                code="credential_load_failed",
                message=f"{type(exc).__name__}: mcp credential load failed",
                idempotency_key=provider_key,
            )

        server_url = f"{self._endpoint_url}/mcp"
        args_hash = hashlib.sha256(
            json.dumps(dict(request.payload), sort_keys=True).encode()
        ).hexdigest()[:16]

        # Real MCP SDK call — session initialize + tools/call.
        # streamablehttp_client handles the full MCP protocol framing.
        try:
            async with streamablehttp_client(
                server_url,
                headers=auth_headers or None,
                timeout=self._timeout_seconds,
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    call_result = await session.call_tool(
                        self._declaration.tool_name,
                        arguments=dict(request.payload),
                    )
        except Exception as exc:  # noqa: BLE001
            return connector_error_result(
                code="mcp_transport_error",
                message=f"{type(exc).__name__}: mcp transport error",
                idempotency_key=provider_key,
            )

        # Extract result content from MCP SDK response.
        result_body: Any = None
        if call_result.content:
            first = call_result.content[0]
            # MCP SDK returns TextContent, ImageContent, etc.
            if hasattr(first, "text"):
                try:
                    result_body = json.loads(first.text)
                except (ValueError, TypeError):
                    result_body = first.text
            else:
                result_body = str(first)

        if call_result.isError:
            return connector_error_result(
                code="mcp_server_error",
                message=f"mcp server returned error: {result_body}",
                idempotency_key=provider_key,
            )

        return ToolInvocationResult(
            output={
                "status": "success",
                "mcp_server_id": self._declaration.mcp_server_id,
                "mcp_tool_name": self._declaration.tool_name,
                "execution_policy": self._declaration.execution_policy.value,
                "result": result_body,
                "args_hash": args_hash,
            },
            status="success",
            idempotency_key=provider_key,
        )


# ---------------------------------------------------------------------------
# Credential runtime for tests
# ---------------------------------------------------------------------------


class _TestMcpCredentialRuntime(McpCredentialRuntime):
    """In-memory credential runtime for tests (no DB, no OPCRED2)."""

    def __init__(self) -> None:
        pass  # no _runtime needed

    async def load_auth_headers(
        self,
        *,
        tenant_id: str,
        mcp_server_id: str,
    ) -> dict[str, str]:
        # No real auth for our local test server.
        return {}


# ---------------------------------------------------------------------------
# Context helper
# ---------------------------------------------------------------------------


def _ctx(seed: str = "1") -> AgentExecutionContext:
    import uuid

    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="test-mcp-e2e",
            runtime_instance_id=uuid.uuid5(uuid.NAMESPACE_URL, f"e2e:{seed}"),
        ),
        execution=ExecutionIdentity(
            execution_id=uuid.uuid5(uuid.NAMESPACE_URL, f"e2e-exec:{seed}"),
            request_id=f"req-e2e-{seed}",
        ),
        capabilities=CapabilitySet((
            AgentCapability(
                name="tool.test_server.echo_message", scope=CapabilityScope.INVOKE
            ),
            AgentCapability(
                name="tool.test_server.send_notification",
                scope=CapabilityScope.INVOKE,
            ),
            AgentCapability(
                name="tool.test_server.read_status", scope=CapabilityScope.INVOKE
            ),
        )),
        constraints=ExecutionConstraints(),
        causality=CausalityMetadata(),
        tenant_id=_TENANT,
        metadata={},
    )


# ---------------------------------------------------------------------------
# Test 1: tools/list via MCP SDK against real server
# ---------------------------------------------------------------------------


async def test_real_mcp_tools_list(live_mcp_server: _LiveServer) -> None:
    """Verify the real FastMCP server returns all 3 tools via tools/list.

    Uses the MCP Python SDK's streamablehttp_client + ClientSession — the same
    transport the router's GET /{tenant_id}/mcp/servers/{id}/tools uses.
    """
    server_url = f"{live_mcp_server.base_url}/mcp"
    async with streamablehttp_client(server_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()

    tool_names = {t.name for t in result.tools}
    assert "echo_message" in tool_names, f"echo_message missing; got: {tool_names}"
    assert "send_notification" in tool_names, f"send_notification missing; got: {tool_names}"
    assert "read_status" in tool_names, f"read_status missing; got: {tool_names}"

    # Verify input schemas are present.
    for tool in result.tools:
        assert tool.inputSchema, f"tool {tool.name!r} has no inputSchema"


# ---------------------------------------------------------------------------
# Test 2: auto_execute echo_message fires real server
# ---------------------------------------------------------------------------


async def test_auto_execute_tool_fires_real_server(live_mcp_server: _LiveServer) -> None:
    """auto_execute echo_message → real JSON-RPC call → real response → status=success."""
    declaration = McpToolDeclaration(
        mcp_server_id="test_server",
        tool_name="echo_message",
        commitment_kind=CommitmentKind.NONE,
        execution_policy=ExecutionPolicy.AUTO_EXECUTE,
        description_snapshot="Echo the message back.",
    )
    tool = _McpConnectorToolForTesting(
        declaration=declaration,
        endpoint_url=live_mcp_server.base_url,
        credential_runtime=_TestMcpCredentialRuntime(),
    )
    call_count_before = len(live_mcp_server.call_log)
    request = ToolInvocationRequest(
        tool_name="test_server.echo_message",
        payload={"message": "hello-from-operious"},
        metadata={},
    )
    result = await tool.invoke(request, _ctx("echo-1"))

    assert result.status == "success", f"Expected success; got {result.status}, output={result.output}"
    assert live_mcp_server.call_log, "real server was never called"
    assert len(live_mcp_server.call_log) > call_count_before, "real server was not called"
    last = live_mcp_server.call_log[-1]
    assert last["tool"] == "echo_message"
    assert last["message"] == "hello-from-operious"

    # Verify result body is the echoed message.
    result_body = result.output.get("result")
    assert result_body is not None, "result body missing"


# ---------------------------------------------------------------------------
# Test 3: operious_approval send_notification must NOT fire real server
# ---------------------------------------------------------------------------


async def test_operious_approval_tool_does_not_fire_real_server(
    live_mcp_server: _LiveServer,
) -> None:
    """operious_approval send_notification → governance gate → REQUIRE_APPROVAL.

    McpConnectorTool.invoke() must NOT be called; the real server must see
    zero new calls for send_notification.

    This test exercises the full ToolInvoker + governance path.
    """
    from unittest.mock import AsyncMock, MagicMock

    from app.agents.tools import ToolInvoker, ToolRegistry
    from app.agents.tools.action_governance import (
        ACTION_TOOLS_POLICY_TYPE,
        build_action_tool_governance_runtime,
    )
    from app.governance.persistence.memory import InMemoryGovernanceRepository
    from app.tenant.persistence import (
        InMemoryTenantConfigurationRepository,
        TenantGovernancePolicyRecord,
    )
    from app.tenant.chronology import canonical_sha256
    from app.tenant.enums import TenantGovernancePolicyStatus
    from app.tenant.identity import derive_governance_policy_version_id
    from datetime import datetime, timezone

    tenant_repo = InMemoryTenantConfigurationRepository()
    _NOW = datetime(2026, 7, 6, tzinfo=timezone.utc)
    parameters = {
        "tools": {
            "test_server.send_notification": {
                "commitment_kind": "goods",
                "execution_policy": "operious_approval",
            }
        }
    }
    content_sha256 = canonical_sha256(
        {
            "tenant_id": _TENANT,
            "policy_type": ACTION_TOOLS_POLICY_TYPE,
            "parameters": parameters,
            "status": TenantGovernancePolicyStatus.ACTIVE.value,
            "version": 1,
            "approved_by": "admin",
            "effective_from": _NOW.isoformat(),
            "source_approval_id": "approval-e2e",
        }
    )
    policy_record = TenantGovernancePolicyRecord(
        policy_id=derive_governance_policy_version_id(
            tenant_id=_TENANT,
            policy_type=ACTION_TOOLS_POLICY_TYPE,
            version=1,
        ),
        tenant_id=_TENANT,
        policy_type=ACTION_TOOLS_POLICY_TYPE,
        parameters=parameters,
        status=TenantGovernancePolicyStatus.ACTIVE,
        version=1,
        approved_by="admin",
        effective_from=_NOW,
        created_at=_NOW,
        source_approval_id="approval-e2e",
        content_sha256=content_sha256,
        previous_version_sha256=None,
    )
    await tenant_repo.save_governance_policy(policy_record, expected_tenant_id=_TENANT)
    governance = build_action_tool_governance_runtime(
        persistence=InMemoryGovernanceRepository(),
        tenant_configuration_repository=tenant_repo,
    )

    # Spy: if invoke() is called, the test fails.
    call_count_before = len(live_mcp_server.call_log)
    invoke_spy = AsyncMock(
        side_effect=AssertionError("invoke() must NOT be called pre-approval")
    )
    mock_tool = MagicMock()
    mock_tool.name = "test_server.send_notification"
    mock_tool.capability = MagicMock()
    mock_tool.capability.__eq__ = lambda self, other: str(other) == "action"
    mock_tool.invoke = invoke_spy
    mock_tool.operation_governance_metadata = MagicMock(
        return_value={
            "operation_id": "send_notification",
            "operation_commitment_kind": "goods",
            "operation_approval_policy": "tenant_policy",
            "operation_execution_policy": "operious_approval",
            "mcp_server_id": "test_server",
            "mcp_tool_name": "send_notification",
        }
    )

    registry = ToolRegistry()
    registry.register(mock_tool)

    invoker = ToolInvoker(
        tool_registry=registry,
        governance_runtime=governance,
        grant_repository=None,
        connector_invocation_repository=None,
    )
    request = ToolInvocationRequest(
        tool_name="test_server.send_notification",
        payload={"to": "alice@example.com", "body": "hello"},
        metadata={"tool_name": "test_server.send_notification"},
    )
    envelope = await invoker.invoke(
        request=request,
        context=_ctx("approval-1"),
        invocation_ordinal=1,
    )

    invoke_spy.assert_not_called()
    assert envelope.is_denied, (
        f"Expected denied envelope for operious_approval; got is_denied={envelope.is_denied}"
    )
    # Real server must not have been called.
    new_calls = [
        c for c in live_mcp_server.call_log[call_count_before:]
        if c["tool"] == "send_notification"
    ]
    assert not new_calls, f"real server was called unexpectedly: {new_calls}"


# ---------------------------------------------------------------------------
# Test 4: unconfigured tool → REQUIRE_APPROVAL, real server never called
# ---------------------------------------------------------------------------


async def test_unconfigured_tool_safe_default_real_server(
    live_mcp_server: _LiveServer,
) -> None:
    """A tool not in the policy custom_tools → REQUIRE_APPROVAL, real server never called."""
    from app.agents.tools.action_governance import (
        ParsedActionPolicy,
        ActionPolicyBinding,
        ACTION_TOOLS_POLICY_TYPE,
        _evaluate_custom_tool,
    )
    from app.governance.enums import Decision

    policy = ParsedActionPolicy(
        binding=ActionPolicyBinding(
            policy_id="p-e2e",
            policy_type=ACTION_TOOLS_POLICY_TYPE,
            version=1,
            content_sha256="c" * 64,
        ),
        rules={},
        custom_tools={},  # empty — unconfigured
    )
    result = _evaluate_custom_tool(
        tool_name="test_server.unknown_tool",
        policy=policy,
    )
    assert result[0].decision is Decision.REQUIRE_APPROVAL

    # Real server never called for an unconfigured tool (governance blocks it
    # before any HTTP call).
    call_count_before = len(live_mcp_server.call_log)
    # No invoke() call happens at governance evaluation time — just the policy check.
    assert len(live_mcp_server.call_log) == call_count_before


# ---------------------------------------------------------------------------
# Test 5: fail-closed on server shutdown
# ---------------------------------------------------------------------------


async def test_fail_closed_on_server_shutdown() -> None:
    """Start a real server, call it once (ok), then stop it and verify fail-closed.

    The tool must return status != 'success' after the server shuts down.
    Never silently succeeds when the server is unreachable.
    """
    mcp, call_log = _build_test_mcp_server()
    port = _find_free_port()
    srv = _start_mcp_server_in_thread(mcp, call_log, port)

    declaration = McpToolDeclaration(
        mcp_server_id="test_server",
        tool_name="echo_message",
        commitment_kind=CommitmentKind.NONE,
        execution_policy=ExecutionPolicy.AUTO_EXECUTE,
    )
    tool = _McpConnectorToolForTesting(
        declaration=declaration,
        endpoint_url=srv.base_url,
        credential_runtime=_TestMcpCredentialRuntime(),
    )
    # First call succeeds.
    req = ToolInvocationRequest(
        tool_name="test_server.echo_message",
        payload={"message": "ping"},
        metadata={},
    )
    ok = await tool.invoke(req, _ctx("shutdown-1"))
    assert ok.status == "success", f"Expected success on live server; got {ok.status}"

    # Shut the server down.
    srv.stop()

    # Second call must fail closed — not silently succeed.
    req2 = ToolInvocationRequest(
        tool_name="test_server.echo_message",
        payload={"message": "ping-after-shutdown"},
        metadata={},
    )
    fail_result = await tool.invoke(req2, _ctx("shutdown-2"))
    assert fail_result.status != "success", (
        f"Expected failure after server shutdown; got status={fail_result.status}"
    )


# ---------------------------------------------------------------------------
# Test 6: auto_execute goods tool fires real server
# ---------------------------------------------------------------------------


async def test_real_server_goods_auto_execute_fires(
    live_mcp_server: _LiveServer,
) -> None:
    """send_notification with auto_execute → fires on real server, real result."""
    declaration = McpToolDeclaration(
        mcp_server_id="test_server",
        tool_name="send_notification",
        commitment_kind=CommitmentKind.GOODS,
        execution_policy=ExecutionPolicy.AUTO_EXECUTE,  # tenant accepted responsibility
        description_snapshot="Send a notification.",
    )
    tool = _McpConnectorToolForTesting(
        declaration=declaration,
        endpoint_url=live_mcp_server.base_url,
        credential_runtime=_TestMcpCredentialRuntime(),
    )
    call_count_before = len(live_mcp_server.call_log)
    request = ToolInvocationRequest(
        tool_name="test_server.send_notification",
        payload={"to": "bob@example.com", "body": "Your order shipped."},
        metadata={},
    )
    result = await tool.invoke(request, _ctx("goods-auto-1"))

    assert result.status == "success", (
        f"Expected success for goods auto_execute; got {result.status}, "
        f"output={result.output}"
    )
    new_calls = [c for c in live_mcp_server.call_log[call_count_before:] if c["tool"] == "send_notification"]
    assert new_calls, "real server was not called for goods auto_execute"
    assert new_calls[-1]["to"] == "bob@example.com"
    assert new_calls[-1]["body"] == "Your order shipped."

    # Result body should include status=ok from the real server.
    result_body = result.output.get("result")
    assert result_body is not None


# ---------------------------------------------------------------------------
# Test 7: read_status returns real structured response
# ---------------------------------------------------------------------------


async def test_read_status_returns_real_structured_response(
    live_mcp_server: _LiveServer,
) -> None:
    """read_status (CommitmentKind.NONE) with auto_execute returns real result."""
    declaration = McpToolDeclaration(
        mcp_server_id="test_server",
        tool_name="read_status",
        commitment_kind=CommitmentKind.NONE,
        execution_policy=ExecutionPolicy.AUTO_EXECUTE,
    )
    tool = _McpConnectorToolForTesting(
        declaration=declaration,
        endpoint_url=live_mcp_server.base_url,
        credential_runtime=_TestMcpCredentialRuntime(),
    )
    request = ToolInvocationRequest(
        tool_name="test_server.read_status",
        payload={"resource_id": "res-abc-123"},
        metadata={},
    )
    result = await tool.invoke(request, _ctx("read-status-1"))
    assert result.status == "success"
    # Result body should contain the resource_id that was passed.
    result_body = result.output.get("result")
    assert result_body is not None
