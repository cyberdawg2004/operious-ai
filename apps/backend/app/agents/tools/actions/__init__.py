"""Governed stub action tools for external customer operations."""

from __future__ import annotations

from app.agents.tools.actions.refund_request import RefundRequestTool
from app.agents.tools.actions.replacement_order import ReplacementOrderTool
from app.agents.tools.actions.warehouse_repair import WarehouseRepairReportTool
from app.agents.tools.actions.warranty_claim import WarrantyClaimTool
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


__all__ = [
    "RefundRequestTool",
    "ReplacementOrderTool",
    "WarehouseRepairReportTool",
    "WarrantyClaimTool",
    "build_action_tool_registry",
]
