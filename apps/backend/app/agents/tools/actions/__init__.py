"""Governed stub action tools for external customer operations."""

from __future__ import annotations

import ssl

from app.agents.tools.actions.refund_request import RefundRequestTool
from app.agents.tools.actions.replacement_order import ReplacementOrderTool
from app.agents.tools.actions.warehouse_repair import WarehouseRepairReportTool
from app.agents.tools.actions.warranty_claim import WarrantyClaimTool
from app.agents.tools.connectors import (
    ConnectorConfigRepository,
    GenericRestRefundConnector,
    SSRFValidator,
    TenantCredentialRuntime,
)
from app.agents.tools.registry import ToolRegistry


def build_action_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool in (
        WarrantyClaimTool(),
        ReplacementOrderTool(),
        RefundRequestTool(),
        WarehouseRepairReportTool(),
    ):
        registry.register(tool)
    return registry


async def build_tenant_action_tool_registry(
    *,
    tenant_id: str,
    config_repository: ConnectorConfigRepository,
    credential_runtime: TenantCredentialRuntime,
    ssl_context: ssl.SSLContext | None = None,
    ssrf_validator: SSRFValidator | None = None,
) -> ToolRegistry:
    """Build one action registry for a tenant's configured connectors."""

    registry = ToolRegistry()
    registry.register(WarrantyClaimTool())
    registry.register(ReplacementOrderTool())
    if await config_repository.get_active_config(
        tenant_id=tenant_id,
        tool_name=GenericRestRefundConnector.name,
        expected_tenant_id=tenant_id,
    ):
        registry.register(
            GenericRestRefundConnector(
                config_repository=config_repository,
                credential_runtime=credential_runtime,
                ssl_context=ssl_context,
                ssrf_validator=ssrf_validator,
            )
        )
    else:
        registry.register(RefundRequestTool())
    registry.register(WarehouseRepairReportTool())
    return registry


__all__ = [
    "RefundRequestTool",
    "ReplacementOrderTool",
    "WarehouseRepairReportTool",
    "WarrantyClaimTool",
    "build_action_tool_registry",
    "build_tenant_action_tool_registry",
]
