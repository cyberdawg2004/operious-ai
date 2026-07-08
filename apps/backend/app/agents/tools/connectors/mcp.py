"""MCP (Model Context Protocol) connector tool.

Adapts an external MCP server's tools to the same governance seam as
GenericConnectorTool: every invocation flows through TenantActionPolicy.evaluate(),
the ConnectorInvocationRepository ledger, and emits a reconstructable
OperationalEvent.

Execution model (tenant-declared per tool):
  auto_execute       — fire immediately; no Operious gate.
                       Fully supported for ALL commitment kinds, including
                       money/goods. The tenant's system owns downstream
                       authorization. Audited with execution_policy=auto_execute.
  operious_approval  — route to Operious human queue before firing.
  Unconfigured tool  — safe default (operious_approval) for unknown tools.

The governance gate (TenantActionPolicy) interprets ExecutionPolicy.AUTO_EXECUTE
in the CustomToolDeclaration as Decision.ALLOW, so McpConnectorTool.invoke() is
reached and fires.  For operious_approval tools, Decision.REQUIRE_APPROVAL is
returned by the gate and invoke() is never called — same as any other governed tool.

Transport: JSON-RPC 2.0 over HTTPS (the MCP transport layer). Every outbound call
goes through the same SSRF guard and IP-pinned transport as GenericConnectorTool.

Credentials: resolved from ConnectorOAuthTokenRuntime (OAuth) or
ConnectorScopedCredentialRuntime (API key), both using OPCRED2.

Fail-closed on ALL transport errors: McpTransportError / timeout / malformed
response → ToolInvocationResult(status="provider_error"). Never silently succeeds.

Real OAuth accounts required for live verification. A mock MCP server (local
HTTP service returning JSON-RPC 2.0 responses) suffices for all governance
invariant tests.
"""

from __future__ import annotations

import hashlib
import json
import logging
import ssl
from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.agents.context import AgentExecutionContext
from app.agents.results import ToolInvocationRequest, ToolInvocationResult
from app.agents.tools.base import BaseTool
from app.agents.tools.capability import ToolCapability
from app.agents.tools.connectors.base import (
    SSRFValidator,
    connector_error_result,
    validate_connector_endpoint_url,
)
from app.agents.tools.connectors.credentials import ConnectorScopedCredentialRuntime
from app.agents.tools.grants import AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY
from app.agents.tools.operation_metadata import (
    APPROVAL_POLICY_METADATA_KEY,
    COMMITMENT_KIND_METADATA_KEY,
    EXECUTION_POLICY_METADATA_KEY,
    OPERATION_ID_METADATA_KEY,
    ApprovalPolicy,
    CommitmentKind,
    ExecutionPolicy,
    MCP_MONEY_GOODS_TRIGGER_PATTERNS,
)
from app.core.http import create_isolated_http_client  # noqa: F401 (patched in tests)
from app.core.ssrf import PinnedIPAsyncHTTPTransport, validate_public_https_url  # noqa: F401 (PinnedIPAsyncHTTPTransport patched in tests)
from app.types.json import JsonObject

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 15.0
_MCP_JSONRPC_VERSION = "2.0"

# Metadata key carrying the MCP server URL for audit/reconstruction.
MCP_SERVER_URL_METADATA_KEY = "mcp_server_url"
MCP_TOOL_NAME_METADATA_KEY = "mcp_tool_name"
MCP_SERVER_ID_METADATA_KEY = "mcp_server_id"
MCP_ARGS_HASH_METADATA_KEY = "mcp_args_hash"
MCP_DESCRIPTION_SNAPSHOT_HASH_KEY = "mcp_description_snapshot_hash"


def _empty_input_schema_snapshot() -> dict[str, Any]:
    return {}


class McpTransportError(RuntimeError):
    """MCP server unreachable, returned non-200, or response is not valid JSON-RPC."""


class McpServerError(RuntimeError):
    """MCP server returned a JSON-RPC error object."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"mcp_server_error code={code}: {message}")
        self.code = code
        self.mcp_message = message


@dataclass(frozen=True, slots=True)
class McpToolDeclaration:
    """Tenant-declared classification for a single MCP server tool.

    Stored in the MCP_SERVER ConnectorConfigRecord payload under
    ``mcp_tools`` as a list of serialized McpToolDeclaration entries.

    Fields:
      mcp_server_id          — matches the connector_id for this server.
      tool_name              — as reported by the MCP server (tools/list).
      commitment_kind        — tenant's classification (informational/audit).
      execution_policy       — auto_execute or operious_approval.
      description_snapshot   — tool description at classify time (for audit).
      input_schema_snapshot  — inputSchema at classify time (for audit).
      enabled                — whether this tool is active in the registry.
    """
    mcp_server_id: str
    tool_name: str
    commitment_kind: CommitmentKind
    execution_policy: ExecutionPolicy
    description_snapshot: str = ""
    input_schema_snapshot: dict[str, Any] = field(
        default_factory=_empty_input_schema_snapshot
    )
    enabled: bool = True

    def description_snapshot_hash(self) -> str:
        return hashlib.sha256(self.description_snapshot.encode()).hexdigest()

    def has_money_goods_trigger(self) -> bool:
        """Return True if name or description matches a money/goods heuristic."""
        combined = (self.tool_name + " " + self.description_snapshot).lower()
        return any(t in combined for t in MCP_MONEY_GOODS_TRIGGER_PATTERNS)

    def effective_commitment_kind(self) -> CommitmentKind:
        """Return the commitment kind to use at synthesis time.

        If the declared kind is below goods but the tool name/description
        matches a money/goods heuristic AND execution_policy is not
        auto_execute (tenant is aware), upgrade to GOODS as a backstop.
        """
        if self.execution_policy is ExecutionPolicy.AUTO_EXECUTE:
            return self.commitment_kind
        _BELOW_GOODS = frozenset({CommitmentKind.NONE, CommitmentKind.RECORD_UPDATE})
        if self.commitment_kind in _BELOW_GOODS and self.has_money_goods_trigger():
            logger.warning(
                "mcp_tool_commitment_kind_upgraded",
                extra={
                    "mcp_server_id": self.mcp_server_id,
                    "tool_name": self.tool_name,
                    "declared_kind": self.commitment_kind.value,
                    "upgraded_to": CommitmentKind.GOODS.value,
                },
            )
            return CommitmentKind.GOODS
        return self.commitment_kind


@dataclass(frozen=True, slots=True)
class McpServerConfig:
    """Runtime configuration for a connected MCP server.

    Loaded from the ConnectorConfigRecord for connector_type="mcp_server".
    endpoint_url is the MCP server's base URL (SSRF-validated at apply time).
    """
    mcp_server_id: str
    endpoint_url: str
    tools: tuple[McpToolDeclaration, ...]
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS

    def get_tool(self, tool_name: str) -> McpToolDeclaration | None:
        for t in self.tools:
            if t.tool_name == tool_name and t.enabled:
                return t
        return None


def parse_mcp_server_config(
    *,
    mcp_server_id: str,
    endpoint_url: str,
    raw_tools: list[dict[str, Any]],
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> McpServerConfig:
    """Parse an McpServerConfig from raw connector config payload data."""
    tools: list[McpToolDeclaration] = []
    for raw in raw_tools:
        try:
            commitment_kind = CommitmentKind(str(raw.get("commitment_kind", "goods")).lower())
        except ValueError:
            commitment_kind = CommitmentKind.GOODS
        try:
            execution_policy = ExecutionPolicy(
                str(raw.get("execution_policy", "operious_approval")).lower()
            )
        except ValueError:
            execution_policy = ExecutionPolicy.OPERIOUS_APPROVAL
        tools.append(McpToolDeclaration(
            mcp_server_id=mcp_server_id,
            tool_name=str(raw.get("tool_name", "")),
            commitment_kind=commitment_kind,
            execution_policy=execution_policy,
            description_snapshot=str(raw.get("description_snapshot", "")),
            input_schema_snapshot=dict(raw.get("input_schema_snapshot") or {}),
            enabled=bool(raw.get("enabled", True)),
        ))
    return McpServerConfig(
        mcp_server_id=mcp_server_id,
        endpoint_url=endpoint_url,
        tools=tuple(tools),
        timeout_seconds=timeout_seconds,
    )


class McpCredentialRuntime:
    """Credential runtime that resolves OAuth tokens for MCP servers.

    Wraps ConnectorScopedCredentialRuntime — the stored credential dict is
    expected to contain at minimum {"access_token": "..."}. Falls back to
    API key auth if the credential dict contains "api_key" instead.
    """

    def __init__(self, *, credential_runtime: ConnectorScopedCredentialRuntime) -> None:
        self._runtime = credential_runtime

    async def load_auth_headers(
        self,
        *,
        tenant_id: str,
        mcp_server_id: str,
    ) -> dict[str, str]:
        """Return Authorization headers for the MCP server call.

        Fail-closed: raises KeyError / PermissionError if no active credential.
        """
        credentials = await self._runtime.load_connector_credentials(
            tenant_id=tenant_id,
            connector_id=mcp_server_id,
        )
        access_token = credentials.get("access_token")
        if access_token and isinstance(access_token, str):
            return {"Authorization": f"Bearer {access_token}"}
        api_key = credentials.get("api_key")
        if api_key and isinstance(api_key, str):
            return {"Authorization": f"Bearer {api_key}"}
        raise KeyError(
            f"no usable auth credential (access_token or api_key) "
            f"for MCP server {mcp_server_id!r}"
        )


class McpConnectorTool(BaseTool):
    """Executes a single MCP tool via JSON-RPC 2.0 over HTTPS.

    Wraps exactly one McpToolDeclaration.  Named f"{mcp_server_id}.{tool_name}"
    so it is registered in the ToolRegistry under the same convention as
    GenericConnectorTool.

    operation_governance_metadata() returns the same keys as OperationDefinition
    .governance_metadata() so TenantActionPolicy.evaluate() (via the custom_tools
    path) works without any changes to the governance gate.

    The governance evaluation path:
      - Tenant policy declares this tool under its full name with commitment_kind
        and execution_policy.
      - _evaluate_custom_tool() resolves Decision from execution_policy:
          auto_execute       → ALLOW (invoke() is called, tool fires)
          operious_approval  → REQUIRE_APPROVAL (invoke() is never called)
      - Unconfigured tool (absent from policy custom_tools) → REQUIRE_APPROVAL.

    Fail-closed on transport errors: McpTransportError / McpServerError /
    timeout / malformed response → ToolInvocationResult(status="provider_error").
    Even an auto_execute tool that encounters a server error fails closed —
    never silently succeeds.
    """

    capability: ClassVar[ToolCapability] = ToolCapability.ACTION

    def __init__(
        self,
        *,
        declaration: McpToolDeclaration,
        endpoint_url: str,
        credential_runtime: McpCredentialRuntime,
        ssl_context: ssl.SSLContext | None = None,
        ssrf_validator: SSRFValidator | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._declaration = declaration
        self._endpoint_url = endpoint_url.rstrip("/")
        self._credential_runtime = credential_runtime
        self._ssl_context = ssl_context
        self._ssrf_validator = ssrf_validator or validate_public_https_url
        self._timeout_seconds = timeout_seconds
        # Canonical name: "{mcp_server_id}.{tool_name}"
        self._name = f"{declaration.mcp_server_id}.{declaration.tool_name}"

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    @property
    def declaration(self) -> McpToolDeclaration:
        return self._declaration

    def operation_governance_metadata(self) -> JsonObject:
        """Return governance metadata envelope — mirrors OperationDefinition.governance_metadata().

        The gate reads COMMITMENT_KIND_METADATA_KEY and APPROVAL_POLICY_METADATA_KEY
        from this dict. EXECUTION_POLICY_METADATA_KEY is included for audit.
        """
        effective_kind = self._declaration.effective_commitment_kind()
        approval_policy = (
            ApprovalPolicy.ALWAYS_REQUIRE_APPROVAL
            if effective_kind in (
                CommitmentKind.MONEY,
                CommitmentKind.GOODS,
                CommitmentKind.SERVICE_COMMITMENT,
            )
            else ApprovalPolicy.TENANT_POLICY
        )
        return {
            OPERATION_ID_METADATA_KEY: self._declaration.tool_name,
            COMMITMENT_KIND_METADATA_KEY: effective_kind.value,
            APPROVAL_POLICY_METADATA_KEY: approval_policy.value,
            EXECUTION_POLICY_METADATA_KEY: self._declaration.execution_policy.value,
            MCP_SERVER_ID_METADATA_KEY: self._declaration.mcp_server_id,
            MCP_TOOL_NAME_METADATA_KEY: self._declaration.tool_name,
            MCP_DESCRIPTION_SNAPSHOT_HASH_KEY: (
                self._declaration.description_snapshot_hash()
            ),
        }

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
    ) -> ToolInvocationResult:
        """Execute the MCP tool via the MCP SDK (streamablehttp_client + ClientSession).

        Uses the full MCP session handshake (initialize → tools/call) as required
        by the Streamable HTTP transport spec. Raw JSON-RPC POST is insufficient —
        the server requires an Mcp-Session-Id established during initialize.

        SSRF guard: validates the endpoint URL before the SDK opens its connection.
        The SDK then calls the same hostname; DNS is assumed stable for the duration
        of the call (standard production assumption for SSRF guards).

        Only reachable after ToolInvoker confirms Decision.ALLOW from the governance
        gate. Fail-closed: any transport or server failure → status="provider_error".
        """
        from app.mcp_integration.client import _get_mcp_session_classes
        ClientSession, streamablehttp_client = _get_mcp_session_classes()

        tenant_id = context.tenant_id
        if not tenant_id:
            return connector_error_result(
                code="missing_tenant",
                message="mcp tool invocation requires tenant_id",
            )

        provider_key = _clean(request.metadata.get(AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY))

        # Load auth credentials.
        try:
            auth_headers = await self._credential_runtime.load_auth_headers(
                tenant_id=tenant_id,
                mcp_server_id=self._declaration.mcp_server_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "mcp_credential_load_failed",
                extra={"tenant_id": tenant_id, "mcp_server_id": self._declaration.mcp_server_id},
                exc_info=True,
            )
            return connector_error_result(
                code="credential_load_failed",
                message=f"{type(exc).__name__}: mcp credential load failed",
                idempotency_key=provider_key,
            )

        # SSRF validation — reject private/loopback IPs before opening the connection.
        # The returned ValidatedPublicHTTPSURL carries the pinned_ip so the transport
        # connects to the exact IP that passed validation, closing the DNS-rebinding
        # and redirect TOCTOU vectors (verifier finding: mcp.py SSRF OPEN).
        mcp_url = f"{self._endpoint_url}/mcp"
        try:
            validated = await validate_connector_endpoint_url(
                validator=self._ssrf_validator,
                url=mcp_url,
                allowed_hosts=(_extract_host(self._endpoint_url),),
            )
        except Exception as exc:  # noqa: BLE001
            return connector_error_result(
                code="ssrf_validation_failed",
                message=f"{type(exc).__name__}: mcp server url failed ssrf validation",
                idempotency_key=provider_key,
            )

        args_hash = hashlib.sha256(
            json.dumps(dict(request.payload), sort_keys=True).encode()
        ).hexdigest()[:16]

        # Build a pinned-IP transport so the SDK never re-resolves DNS and cannot
        # follow redirects to internal hosts.  create_isolated_http_client is the
        # single canonical factory (shared-http-client invariant).
        _pinned_transport = PinnedIPAsyncHTTPTransport(pinned_ip=validated.pinned_ip)
        _pinned_client = create_isolated_http_client(
            transport=_pinned_transport,
            timeout_seconds=self._timeout_seconds,
            follow_redirects=False,
        )

        # MCP SDK call: initialize session then tools/call.
        try:
            async with streamablehttp_client(
                mcp_url,
                headers=auth_headers or None,
                timeout=self._timeout_seconds,
                http_client=_pinned_client,
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    call_result = await session.call_tool(
                        self._declaration.tool_name,
                        arguments=dict(request.payload),
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "mcp_transport_error",
                extra={
                    "tenant_id": tenant_id,
                    "mcp_server_id": self._declaration.mcp_server_id,
                    "tool_name": self._declaration.tool_name,
                    "error": str(exc),
                },
            )
            return connector_error_result(
                code="mcp_transport_error",
                message=f"{type(exc).__name__}: mcp transport error",
                idempotency_key=provider_key,
            )

        if call_result.isError:
            err_text = str(call_result.content[0].text) if call_result.content else "unknown"
            logger.warning(
                "mcp_server_error",
                extra={
                    "tenant_id": tenant_id,
                    "mcp_server_id": self._declaration.mcp_server_id,
                    "tool_name": self._declaration.tool_name,
                    "error_message": err_text,
                },
            )
            return connector_error_result(
                code="mcp_server_error",
                message=f"mcp server returned error: {err_text}",
                idempotency_key=provider_key,
            )

        # Extract result body from MCP SDK content.
        result_body: Any = None
        if call_result.content:
            first = call_result.content[0]
            if hasattr(first, "text"):
                try:
                    result_body = json.loads(first.text)
                except (ValueError, TypeError):
                    result_body = first.text
            else:
                result_body = str(first)

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


def _clean(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _extract_host(url: str) -> str:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return (parsed.hostname or "").lower()


__all__ = [
    "McpConnectorTool",
    "McpCredentialRuntime",
    "McpServerConfig",
    "McpServerError",
    "McpToolDeclaration",
    "McpTransportError",
    "MCP_ARGS_HASH_METADATA_KEY",
    "MCP_DESCRIPTION_SNAPSHOT_HASH_KEY",
    "MCP_SERVER_ID_METADATA_KEY",
    "MCP_SERVER_URL_METADATA_KEY",
    "MCP_TOOL_NAME_METADATA_KEY",
    "parse_mcp_server_config",
]
