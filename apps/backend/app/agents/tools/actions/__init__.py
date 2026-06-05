"""Governed action tools for external customer operations.

Real connectors are registered when a tenant has configured one. For actions
with no configured connector, the registry registers EITHER a fake-success stub
(``allow_stub_actions=True``, e.g. non-production / pilot) OR a fail-closed
governed-error tool (``allow_stub_actions=False``, the production default) so an
agent never tells a customer an action happened when it did not.
"""

from __future__ import annotations

import ssl

from app.agents.tools.actions.fail_closed import FailClosedActionTool
from app.agents.tools.actions.refund_request import RefundRequestTool
from app.agents.tools.actions.replacement_order import ReplacementOrderTool
from app.agents.tools.actions.warehouse_repair import WarehouseRepairReportTool
from app.agents.tools.actions.warranty_claim import WarrantyClaimTool
from app.agents.tools.base import BaseTool
from app.agents.tools.connectors import (
    ConnectorConfigRepository,
    GenericRestRepairDispatchConnector,
    GenericRestRefundConnector,
    SSRFValidator,
    TenantCredentialRuntime,
)
from app.agents.tools.registry import ToolRegistry
from app.work_orders.persistence.repository import WorkOrderRepositoryProtocol


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


def _stub_or_fail_closed(
    stub_cls: type[BaseTool], *, allow_stub_actions: bool, reason: str
) -> BaseTool:
    """Return the fake-success stub (pilot) or a fail-closed error tool (prod)."""
    if allow_stub_actions:
        return stub_cls()
    return FailClosedActionTool(
        name=stub_cls.name,
        capability=stub_cls.capability,
        required_capabilities=stub_cls.required_capabilities,
        reason=reason,
    )


async def build_tenant_action_tool_registry(
    *,
    tenant_id: str,
    config_repository: ConnectorConfigRepository,
    credential_runtime: TenantCredentialRuntime,
    work_order_repository: WorkOrderRepositoryProtocol | None = None,
    ssl_context: ssl.SSLContext | None = None,
    ssrf_validator: SSRFValidator | None = None,
    allow_stub_actions: bool = True,
) -> ToolRegistry:
    """Build one action registry for a tenant's configured connectors.

    ``allow_stub_actions`` defaults to ``True`` for backward compatibility; the
    production caller passes ``settings.allow_stub_actions_effective`` so an
    unconfigured action fails closed in production instead of faking success.
    """

    registry = ToolRegistry()
    registry.register(
        _stub_or_fail_closed(
            WarrantyClaimTool,
            allow_stub_actions=allow_stub_actions,
            reason="warranty connector is not configured for this tenant",
        )
    )
    registry.register(
        _stub_or_fail_closed(
            ReplacementOrderTool,
            allow_stub_actions=allow_stub_actions,
            reason="replacement connector is not configured for this tenant",
        )
    )
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
        registry.register(
            _stub_or_fail_closed(
                RefundRequestTool,
                allow_stub_actions=allow_stub_actions,
                reason="refund connector is not configured for this tenant",
            )
        )
    if work_order_repository is not None and await config_repository.get_active_config(
        tenant_id=tenant_id,
        tool_name=GenericRestRepairDispatchConnector.name,
        expected_tenant_id=tenant_id,
    ):
        registry.register(
            GenericRestRepairDispatchConnector(
                config_repository=config_repository,
                credential_runtime=credential_runtime,
                work_order_repository=work_order_repository,
                ssl_context=ssl_context,
                ssrf_validator=ssrf_validator,
            )
        )
    registry.register(
        _stub_or_fail_closed(
            WarehouseRepairReportTool,
            allow_stub_actions=allow_stub_actions,
            reason="warehouse connector is not configured for this tenant",
        )
    )
    return registry


__all__ = [
    "FailClosedActionTool",
    "RefundRequestTool",
    "ReplacementOrderTool",
    "WarehouseRepairReportTool",
    "WarrantyClaimTool",
    "build_action_tool_registry",
    "build_tenant_action_tool_registry",
]
