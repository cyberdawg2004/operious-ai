"""Stub warranty-claim action tool."""

from __future__ import annotations

from typing import ClassVar

from pydantic import ValidationError

from app.agents.context import AgentExecutionContext
from app.agents.identity import derive_action_idempotency_key
from app.agents.results import ToolInvocationRequest, ToolInvocationResult
from app.agents.tools.action_payloads import WarrantyClaimPayload
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


class WarrantyClaimTool(BaseTool):
    name: ClassVar[str] = "warranty.claim"
    capability: ClassVar[ToolCapability] = ToolCapability.ACTION
    required_capabilities: ClassVar[frozenset[str]] = frozenset(
        {"tool.warranty.claim"}
    )

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
    ) -> ToolInvocationResult:
        try:
            payload = WarrantyClaimPayload.model_validate(request.payload)
        except ValidationError as exc:
            return invalid_payload_result(exc)

        tenant_id = tenant_id_for(context)
        session_id = session_id_for(request, context)
        if tenant_id is None or session_id is None:
            return invalid_context_result(
                "warranty.claim requires tenant_id and session_id"
            )
        target_resource = target_resource_for(
            request,
            f"order:{payload.order_id}:sku:{payload.product_sku}",
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
                f"Warranty claim submitted for order {payload.order_id} (stub)"
            ),
            metadata={
                "order_id": payload.order_id,
                "product_sku": payload.product_sku,
                "issue_category": payload.issue_category,
                "target_resource": target_resource,
            },
        )


__all__ = ["WarrantyClaimTool"]
