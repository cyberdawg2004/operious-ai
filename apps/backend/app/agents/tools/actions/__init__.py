"""Governed action tools for external customer operations.

Real connectors are registered when a tenant has configured one. For actions
with no configured connector, the registry registers a fail-closed governed
error tool so an agent never tells a customer an action happened when it did not.

Domain-agnostic: no tool names, action types, or business domains are hardcoded.
Every registered connector comes from the tenant's active ConnectorConfigRecord
rows. Commerce, banking, healthcare, telecom, MCP servers — all verticals work
through the same generic registration loop.

Money/goods commitment rule:
  For custom REST connectors (connector_type prefix): CommitmentKind is derived
  from the prefix. For MCP tools: CommitmentKind and ExecutionPolicy are declared
  per-tool in the tenant's action_tools policy. Both models are fully audited.

  Unconfigured MCP tool (absent from policy) → REQUIRE_APPROVAL (safe default).
  MCP tool with execution_policy=auto_execute → ALLOW (fires immediately).
  MCP tool with execution_policy=operious_approval → REQUIRE_APPROVAL.
"""

from __future__ import annotations

import ssl
from typing import cast

from app.agents.tools.actions.fail_closed import FailClosedActionTool
from app.agents.tools.actions.refund_request import RefundRequestTool
from app.agents.tools.actions.replacement_order import ReplacementOrderTool
from app.agents.tools.actions.warehouse_repair import WarehouseRepairReportTool
from app.agents.tools.actions.warranty_claim import WarrantyClaimTool
from app.agents.tools.connectors import (
    ChannelBridgedConnectorCredentialRuntime,
    ConnectorConfigRepository,
    ConnectorCredentialRuntime,
    ConnectorDefinition,
    GenericConnectorTool,
    GenericRestRepairDispatchConnector,
    IdempotencyStrategy,
    OperationDefinition,
    OperationMode,
    SSRFValidator,
    TenantCredentialRuntime,
)
from app.agents.tools.connectors.config import ConnectorConfigRecord
from app.agents.tools.connectors.credentials import ConnectorScopedCredentialRuntime
from app.agents.tools.connectors.mcp import (
    McpConnectorTool,
    McpCredentialRuntime,
    McpToolDeclaration,
    parse_mcp_server_config,
)
from app.agents.tools.operation_metadata import (
    ApprovalPolicy,
    CommitmentKind,
)
from app.tenant.enums import TenantChannelType
from app.agents.tools.registry import ToolRegistry
from app.work_orders.persistence.repository import WorkOrderRepositoryProtocol

# connector_type value for MCP servers registered via the MCP_SERVER change type.
MCP_SERVER_CONNECTOR_TYPE = "mcp_server"

# connector_type prefix → (CommitmentKind, ApprovalPolicy).
# Any prefix not listed falls through to the GOODS/ALWAYS_REQUIRE_APPROVAL
# default — fail-closed: an unknown commitment type is treated as a real-goods
# commitment to preserve the money/goods-always-human invariant.
_CONNECTOR_TYPE_COMMITMENT: dict[str, tuple[CommitmentKind, ApprovalPolicy]] = {
    "money": (CommitmentKind.MONEY, ApprovalPolicy.ALWAYS_REQUIRE_APPROVAL),
    "goods": (CommitmentKind.GOODS, ApprovalPolicy.ALWAYS_REQUIRE_APPROVAL),
    "repair": (CommitmentKind.GOODS, ApprovalPolicy.ALWAYS_REQUIRE_APPROVAL),
    "record": (CommitmentKind.RECORD_UPDATE, ApprovalPolicy.TENANT_POLICY),
    "none": (CommitmentKind.NONE, ApprovalPolicy.TENANT_POLICY),
    "read": (CommitmentKind.NONE, ApprovalPolicy.TENANT_POLICY),
}


def build_action_tool_registry() -> ToolRegistry:
    """Build a registry with legacy stub tool instances.

    Used only in direct-construction tests where no DB config is available.
    These are the pre-2.2 tool classes (RefundRequestTool, WarrantyClaimTool,
    etc.) that simulate success. In production, build_tenant_action_tool_registry
    is used, which reads ConnectorConfigRecord rows from the DB.
    """
    registry = ToolRegistry()
    for tool_cls in (
        RefundRequestTool,
        ReplacementOrderTool,
        WarehouseRepairReportTool,
        WarrantyClaimTool,
    ):
        registry.register(tool_cls())
    return registry


async def build_tenant_action_tool_registry(
    *,
    tenant_id: str,
    config_repository: ConnectorConfigRepository,
    credential_runtime: TenantCredentialRuntime,
    connector_credential_runtime: ConnectorScopedCredentialRuntime | None = None,
    work_order_repository: WorkOrderRepositoryProtocol | None = None,
    ssl_context: ssl.SSLContext | None = None,
    ssrf_validator: SSRFValidator | None = None,
    allow_stub_actions: bool = False,
) -> ToolRegistry:
    """Build one action registry driven entirely by the tenant's connector configs.

    Domain-agnostic: no tool name, action type, or business domain is hardcoded.
    Every registered tool comes from an active ConnectorConfigRecord row.

    MCP servers (connector_type="mcp_server") are expanded into one
    McpConnectorTool per enabled, configured tool declaration in the config's
    ``mcp_tools`` payload field. Each MCP tool is registered under the name
    f"{mcp_server_id}.{tool_name}" and flows through TenantActionPolicy just
    like any custom tool — the execution_policy in the declaration drives
    whether the gate returns ALLOW (auto_execute) or REQUIRE_APPROVAL.

    Custom REST connectors (all other connector_type values) continue to use
    GenericConnectorTool with CommitmentKind derived from the connector_type prefix.

    ``connector_credential_runtime`` is used for both custom REST connectors
    and MCP servers (OPCRED2-encrypted per-connector credentials).

    ``allow_stub_actions`` is accepted for API compatibility but has no effect —
    no hardcoded tool stubs exist. Every tool comes from the tenant's DB config.
    """

    registry = ToolRegistry()
    all_configs = await config_repository.list_active_for_tenant(
        tenant_id=tenant_id,
        expected_tenant_id=tenant_id,
    )

    for config in all_configs:
        if config.connector_type.lower() == MCP_SERVER_CONNECTOR_TYPE:
            # MCP server: expand one config row into N McpConnectorTool instances.
            _register_mcp_tools(
                registry=registry,
                config=config,
                connector_credential_runtime=connector_credential_runtime,
                ssl_context=ssl_context,
                ssrf_validator=ssrf_validator,
            )
        else:
            if registry.has(config.tool_name):
                continue  # duplicate tool_name — first wins
            tool = _connector_tool_from_config(
                config=config,
                config_repository=config_repository,
                credential_runtime=credential_runtime,
                connector_credential_runtime=connector_credential_runtime,
                work_order_repository=work_order_repository,
                ssl_context=ssl_context,
                ssrf_validator=ssrf_validator,
            )
            registry.register(tool)

    del allow_stub_actions  # no hardcoded tool stubs; every tool comes from DB config
    return registry


def _register_mcp_tools(
    *,
    registry: ToolRegistry,
    config: ConnectorConfigRecord,
    connector_credential_runtime: ConnectorScopedCredentialRuntime | None,
    ssl_context: ssl.SSLContext | None,
    ssrf_validator: SSRFValidator | None,
) -> None:
    """Expand an MCP server ConnectorConfigRecord into per-tool McpConnectorTool instances.

    The config's endpoint_template is the MCP server base URL.
    The config's field_mappings["mcp_tools"] is a list of tool declarations.

    Tools whose canonical name is already registered are skipped (first wins).
    If connector_credential_runtime is absent, MCP tools are not registered
    (fail-closed: no credential runtime = no tools).
    """
    if connector_credential_runtime is None:
        import logging
        logging.getLogger(__name__).warning(
            "mcp_tools_skipped_no_credential_runtime",
            extra={"connector_type": config.connector_type, "tool_name": config.tool_name},
        )
        return

    mcp_server_id = config.tool_name  # tool_name IS the mcp_server_id for MCP configs
    endpoint_url = config.endpoint_template
    raw_tools = config.field_mappings.get("mcp_tools")
    if not isinstance(raw_tools, list) or not raw_tools:
        return

    mcp_config = parse_mcp_server_config(
        mcp_server_id=mcp_server_id,
        endpoint_url=endpoint_url,
        raw_tools=list(raw_tools),
        timeout_seconds=float(config.field_mappings.get("timeout_seconds", 15.0)),
    )
    mcp_credential_runtime = McpCredentialRuntime(
        credential_runtime=connector_credential_runtime
    )

    for declaration in mcp_config.tools:
        if not declaration.enabled:
            continue
        canonical_name = f"{mcp_server_id}.{declaration.tool_name}"
        if registry.has(canonical_name):
            continue
        tool = McpConnectorTool(
            declaration=declaration,
            endpoint_url=endpoint_url,
            credential_runtime=mcp_credential_runtime,
            ssl_context=ssl_context,
            ssrf_validator=ssrf_validator,
            timeout_seconds=mcp_config.timeout_seconds,
        )
        registry.register(tool)


def _commitment_from_connector_type(
    connector_type: str,
) -> tuple[CommitmentKind, ApprovalPolicy]:
    """Derive CommitmentKind and ApprovalPolicy from a connector_type prefix.

    Convention (case-insensitive prefix match):
      money.*   → MONEY / ALWAYS_REQUIRE_APPROVAL
      goods.*   → GOODS / ALWAYS_REQUIRE_APPROVAL
      repair.*  → GOODS / ALWAYS_REQUIRE_APPROVAL  (repair involves goods delivery)
      record.*  → RECORD_UPDATE / TENANT_POLICY
      none.*    → NONE / TENANT_POLICY
      read.*    → NONE / TENANT_POLICY
      <other>   → GOODS / ALWAYS_REQUIRE_APPROVAL  (fail-closed safe default)
    """
    raw = connector_type.lower()
    for prefix, (kind, policy) in _CONNECTOR_TYPE_COMMITMENT.items():
        if raw.startswith(prefix):
            return kind, policy
    return CommitmentKind.GOODS, ApprovalPolicy.ALWAYS_REQUIRE_APPROVAL


def _connector_tool_from_config(
    *,
    config: ConnectorConfigRecord,
    config_repository: ConnectorConfigRepository,
    credential_runtime: TenantCredentialRuntime,
    connector_credential_runtime: ConnectorScopedCredentialRuntime | None,
    work_order_repository: WorkOrderRepositoryProtocol | None,
    ssl_context: ssl.SSLContext | None,
    ssrf_validator: SSRFValidator | None,
) -> GenericConnectorTool | GenericRestRepairDispatchConnector:
    """Build the appropriate connector tool from a ConnectorConfigRecord.

    Repair-typed connectors (connector_type prefix ``repair``) use
    GenericRestRepairDispatchConnector when a work_order_repository is available
    so that dispatch operations create durable WorkOrderRecords. All other
    connector types use GenericConnectorTool.

    No hardcoded tool names anywhere in this function.
    """
    commitment_kind, approval_policy = _commitment_from_connector_type(
        config.connector_type
    )
    raw_type = config.connector_type.lower()
    if raw_type.startswith("repair") and work_order_repository is not None:
        return GenericRestRepairDispatchConnector(
            config_repository=config_repository,
            credential_runtime=credential_runtime,
            work_order_repository=work_order_repository,
            ssl_context=ssl_context,
            ssrf_validator=ssrf_validator,
        )

    # connector_id must equal config.tool_name so that
    # GenericConnectorTool.name == f"{connector_id}.{operation_id}" resolves
    # to the canonical tool_name used by the governance gate and taxonomy
    # validator. We set operation_id to "" so the combined name is exactly
    # config.tool_name (the dot is stripped by the non-empty guard below).
    # GenericConnectorTool uses connector_id + "." + operation_id; using
    # connector_id=tool_name and operation_id="" yields "tool_name." which
    # still has a trailing dot. Instead: use connector_id=tool_name and a
    # sentinel operation_id so the registry key IS tool_name.
    #
    # The cleanest approach: subclass connector_id to the tool_name itself and
    # use a single-segment operation_id that makes the combined name equal the
    # tool_name. Since GenericConnectorTool._name = f"{connector_id}.{operation_id}",
    # to get exactly config.tool_name we split at the last dot if present:
    #   connector_id = "refund"  operation_id = "request"  → "refund.request" ✓
    #   connector_id = "account" operation_id = "freeze"   → "account.freeze" ✓
    # Split on the last "." in tool_name for multi-segment names.
    tool_name = config.tool_name
    if "." in tool_name:
        last_dot = tool_name.rfind(".")
        cid = tool_name[:last_dot]
        oid = tool_name[last_dot + 1:]
    else:
        cid = tool_name
        oid = "act"

    operation = OperationDefinition(
        operation_id=oid,
        mode=OperationMode.ACT,
        request_mapping=dict(config.field_mappings),
        response_mapping=dict(config.response_parse),
        idempotency_strategy=IdempotencyStrategy.HEADER,
        commitment_kind=commitment_kind,
        approval_policy=approval_policy,
    )
    connector = ConnectorDefinition(
        connector_id=cid,
        protocol="https",
        operations=(operation,),
    )
    return GenericConnectorTool(
        connector=connector,
        operation=operation,
        config_repository=config_repository,
        credential_runtime=_resolve_credential_runtime(
            config=config,
            connector_id=cid,
            channel_credential_runtime=credential_runtime,
            connector_credential_runtime=connector_credential_runtime,
        ),
        ssl_context=ssl_context,
        ssrf_validator=ssrf_validator,
    )


def _resolve_credential_runtime(
    *,
    config: ConnectorConfigRecord,
    connector_id: str,
    channel_credential_runtime: TenantCredentialRuntime,
    connector_credential_runtime: ConnectorScopedCredentialRuntime | None,
) -> ConnectorCredentialRuntime:
    """Resolve the correct credential runtime for a connector.

    Priority:
    1. If the runtime already exposes load_connector_credentials, use it directly.
    2. If connector_credential_runtime is provided AND connector_type is NOT a
       known TenantChannelType, use the per-connector credential store.
       This covers custom (non-commerce) connectors — bank account.freeze,
       telecom service.suspend, etc.
    3. Fall back to ChannelBridgedConnectorCredentialRuntime that maps
       connector_type → TenantChannelType for built-in commerce connectors.
    """
    if hasattr(channel_credential_runtime, "load_connector_credentials"):
        return cast(ConnectorCredentialRuntime, channel_credential_runtime)

    try:
        channel_type = TenantChannelType(config.connector_type)
    except ValueError:
        # Not a known channel type — use per-connector credential store if available.
        if connector_credential_runtime is not None:
            return connector_credential_runtime
        # No per-connector runtime available: fail closed at credential load time.
        connector_channel_map: dict[str, TenantChannelType] = {}
    else:
        connector_channel_map = {connector_id: channel_type}

    return ChannelBridgedConnectorCredentialRuntime(
        channel_credential_loader=channel_credential_runtime,
        connector_channel_map=connector_channel_map,
    )


__all__ = [
    "FailClosedActionTool",
    "MCP_SERVER_CONNECTOR_TYPE",
    "McpConnectorTool",
    "McpCredentialRuntime",
    "McpToolDeclaration",
    "RefundRequestTool",
    "ReplacementOrderTool",
    "WarehouseRepairReportTool",
    "WarrantyClaimTool",
    "build_action_tool_registry",
    "build_tenant_action_tool_registry",
    "ConnectorScopedCredentialRuntime",
]
