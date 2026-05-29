"""Stub refund-request action tool."""

from __future__ import annotations

from typing import ClassVar

from pydantic import ValidationError

from app.agents.context import AgentExecutionContext
from app.agents.identity import derive_action_idempotency_key
from app.agents.results import ToolInvocationRequest, ToolInvocationResult
from app.agents.tools.action_payloads import RefundRequestPayload
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


class RefundRequestTool(BaseTool):
    name: ClassVar[str] = "refund.request"
    capability: ClassVar[ToolCapability] = ToolCapability.ACTION
    required_capabilities: ClassVar[frozenset[str]] = frozenset(
        {"tool.refund.request"}
    )

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
    ) -> ToolInvocationResult:
        try:
            payload = RefundRequestPayload.model_validate(request.payload)
        except ValidationError as exc:
            return invalid_payload_result(exc)

        tenant_id = tenant_id_for(context)
        session_id = session_id_for(request, context)
        if tenant_id is None or session_id is None:
            return invalid_context_result(
                "refund.request requires tenant_id and session_id"
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
                f"Refund request prepared for order {payload.order_id} (stub)"
            ),
            metadata={
                "order_id": payload.order_id,
                "product_sku": payload.product_sku,
                "refund_amount_cents": payload.refund_amount_cents,
                "refund_reason": payload.refund_reason,
                "target_resource": target_resource,
            },
        )


__all__ = ["RefundRequestTool"]
