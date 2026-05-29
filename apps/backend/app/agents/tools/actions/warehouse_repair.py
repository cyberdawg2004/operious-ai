"""Stub warehouse repair-report action tool."""

from __future__ import annotations

from typing import ClassVar

from pydantic import ValidationError

from app.agents.context import AgentExecutionContext
from app.agents.identity import derive_action_idempotency_key
from app.agents.results import ToolInvocationRequest, ToolInvocationResult
from app.agents.tools.action_payloads import WarehouseRepairReportPayload
from app.agents.tools.actions._shared import (
    invalid_context_result,
    invalid_payload_result,
    session_id_for,
    success_result,
    target_resource_for,
    tenant_id_for,
)
from app.agents.tools.base import BaseTool
from app.agents.tools.capability import ToolCapability


class WarehouseRepairReportTool(BaseTool):
    name: ClassVar[str] = "warehouse.repair.report"
    capability: ClassVar[ToolCapability] = ToolCapability.ACTION
    required_capabilities: ClassVar[frozenset[str]] = frozenset(
        {"tool.warehouse.repair"}
    )

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
    ) -> ToolInvocationResult:
        try:
            payload = WarehouseRepairReportPayload.model_validate(
                request.payload
            )
        except ValidationError as exc:
            return invalid_payload_result(exc)

        tenant_id = tenant_id_for(context)
        session_id = session_id_for(request, context, fallback=payload.session_id)
        if tenant_id is None or session_id is None:
            return invalid_context_result(
                "warehouse.repair.report requires tenant_id and session_id"
            )
        batch = payload.batch_id or "unknown"
        target_resource = target_resource_for(
            request,
            f"sku:{payload.product_sku}:batch:{batch}",
        )
        idempotency_key = derive_action_idempotency_key(
            tenant_id=tenant_id,
            session_id=session_id,
            tool_name=self.name,
            target_resource=target_resource,
        )
        return success_result(
            tool_name=self.name,
            idempotency_key=idempotency_key,
            result_summary=(
                "Warehouse repair report prepared for "
                f"{payload.product_sku} (stub)"
            ),
            metadata={
                "product_sku": payload.product_sku,
                "batch_id": payload.batch_id,
                "severity": payload.severity,
                "target_resource": target_resource,
            },
        )


__all__ = ["WarehouseRepairReportTool"]
