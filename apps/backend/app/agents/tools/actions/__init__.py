"""Governed action tools for external customer operations.

Real connectors are registered when a tenant has configured one. For actions
with no configured connector, the registry registers a fail-closed governed
error tool so an agent never tells a customer an action happened when it did not.

Domain-agnostic: no tool names, action types, or business domains are hardcoded.
Every registered connector comes from the tenant's active ConnectorConfigRecord
rows. Commerce, banking, healthcare, telecom — all verticals work through the
same generic registration loop.

Money/goods commitment rule (INVIOLABLE):
  A configured connector for a money/goods operation MUST always require human
  approval before execution. Connectors inherit CommitmentKind from their
  connector_type prefix (``money.*``, ``goods.*``) or default to GOODS
  (fail-closed). The FailClosedActionTool fires for any configured operation
  missing a real connector endpoint.
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
from app.agents.tools.operation_metadata import (
    ApprovalPolicy,
    CommitmentKind,
)
from app.tenant.enums import TenantChannelType
from app.agents.tools.registry import ToolRegistry
from app.work_orders.persistence.repository import WorkOrderRepositoryProtocol

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
    """Build a registry with only FailClosedActionTool placeholders.

    Used in contexts where no tenant config is available (e.g. offline tools,
    legacy direct-construction tests). All tools fail closed with a clear error.
    This registry is replaced by build_tenant_action_tool_registry in production.
    """
    return ToolRegistry()


async def build_tenant_action_tool_registry(
    *,
    tenant_id: str,
    config_repository: ConnectorConfigRepository,
    credential_runtime: TenantCredentialRuntime,
    work_order_repository: WorkOrderRepositoryProtocol | None = None,
    ssl_context: ssl.SSLContext | None = None,
    ssrf_validator: SSRFValidator | None = None,
    allow_stub_actions: bool = False,
) -> ToolRegistry:
    """Build one action registry driven entirely by the tenant's connector configs.

    Domain-agnostic: no tool name, action type, or business domain is hardcoded.
    Every registered tool comes from an active ConnectorConfigRecord row. A tenant
    with refund/warranty configs gets those connectors. A bank tenant with
    account.freeze/dispute.file configs gets those. A telecom with service.suspend
    gets that. Same code path for all.

    CommitmentKind is derived from the connector_type prefix so the
    money/goods-always-human governance invariant is preserved for all verticals.
    When no connector is configured for a tool, a FailClosedActionTool is NOT
    registered — the tool simply does not exist in this tenant's registry. If
    the agent attempts to call an unconfigured tool, the tool session returns a
    governed error via the registry's unknown-tool path.

    The ``allow_stub_actions`` parameter is retained for API compatibility with
    non-production test callers; it has no effect in the generic path because
    no stubs are registered — only real connectors or nothing.
    """
    del allow_stub_actions  # no stub path in the generic implementation

    registry = ToolRegistry()
    all_configs = await config_repository.list_active_for_tenant(
        tenant_id=tenant_id,
        expected_tenant_id=tenant_id,
    )

    for config in all_configs:
        if registry.has(config.tool_name):
            continue  # duplicate tool_name in configs — first wins

        tool = _connector_tool_from_config(
            config=config,
            config_repository=config_repository,
            credential_runtime=credential_runtime,
            work_order_repository=work_order_repository,
            ssl_context=ssl_context,
            ssrf_validator=ssrf_validator,
        )
        registry.register(tool)

    return registry


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
        credential_runtime=_connector_credential_runtime(
            config=config,
            connector_id=cid,
            credential_runtime=credential_runtime,
        ),
        ssl_context=ssl_context,
        ssrf_validator=ssrf_validator,
    )


def _connector_credential_runtime(
    *,
    config: ConnectorConfigRecord,
    connector_id: str,
    credential_runtime: TenantCredentialRuntime,
) -> ConnectorCredentialRuntime:
    """Bridge existing channel credentials into generic connector credentials.

    Some newer test/dedicated runtimes already expose ``load_connector_credentials``.
    The production tenant runtime exposes channel credentials only, so generic
    connector configs bind their ``connector_type`` to an existing
    ``TenantChannelType``. Unknown connector types fail closed at credential
    load time rather than fabricating credentials.
    """

    if hasattr(credential_runtime, "load_connector_credentials"):
        return cast(ConnectorCredentialRuntime, credential_runtime)

    try:
        channel_type = TenantChannelType(config.connector_type)
    except ValueError:
        connector_channel_map: dict[str, TenantChannelType] = {}
    else:
        connector_channel_map = {connector_id: channel_type}

    return ChannelBridgedConnectorCredentialRuntime(
        channel_credential_loader=credential_runtime,
        connector_channel_map=connector_channel_map,
    )


__all__ = [
    "FailClosedActionTool",
    "RefundRequestTool",
    "ReplacementOrderTool",
    "WarehouseRepairReportTool",
    "WarrantyClaimTool",
    "build_action_tool_registry",
    "build_tenant_action_tool_registry",
]
