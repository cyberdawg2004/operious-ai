"""Stub action tool classes for direct-construction tests.

These tools simulate success without calling any real connector. They are
used ONLY by tests that build a ToolRegistry directly (without a DB-backed
ConnectorConfigRecord). Production code NEVER imports from this module.

The production path (build_tenant_action_tool_registry) reads only from
ConnectorConfigRecord rows and never registers these classes.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from pydantic import ValidationError

from app.agents.context import AgentExecutionContext
from app.agents.identity import derive_action_idempotency_key
from app.agents.results import ToolInvocationRequest, ToolInvocationResult
from app.agents.tools.action_payloads import (
    RefundRequestPayload,
    ReplacementOrderPayload,
    WarehouseRepairReportPayload,
    WarrantyClaimPayload,
)
from app.agents.tools.base import BaseTool
from app.agents.tools.capability import ToolCapability


# ---------------------------------------------------------------------------
# Shared helpers (previously in app/agents/tools/actions/_shared.py)
# ---------------------------------------------------------------------------

def _invalid_payload_result(exc: ValidationError) -> ToolInvocationResult:
    return ToolInvocationResult(
        output={"status": "error", "error_code": "invalid_payload"},
        status="error",
        error_code="invalid_payload",
        error_message=str(exc),
    )


def _invalid_context_result(message: str) -> ToolInvocationResult:
    return ToolInvocationResult(
        output={"status": "error", "error_code": "invalid_context"},
        status="error",
        error_code="invalid_context",
        error_message=message,
    )


def _session_id_for(
    request: ToolInvocationRequest,
    context: AgentExecutionContext,
    *,
    fallback: str | None = None,
) -> str | None:
    def _text(value: object) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() else None

    return (
        _text(request.metadata.get("session_id"))
        or _text(context.metadata.get("session_id"))
        or fallback
    )


def _target_resource_for(request: ToolInvocationRequest, default: str) -> str:
    value = request.metadata.get("target_resource")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _tenant_id_for(context: AgentExecutionContext) -> str | None:
    value = context.tenant_id
    return value.strip() if isinstance(value, str) and value.strip() else None


def _stub_success_result(
    *,
    tool_name: str,
    idempotency_key: uuid.UUID,
    result_summary: str,
    metadata: dict[str, Any],
) -> ToolInvocationResult:
    return ToolInvocationResult(
        output={
            "status": "success",
            "idempotency_key": str(idempotency_key),
            "result_summary": result_summary,
        },
        metadata={**metadata, "tool": tool_name, "stub": True},
        status="success",
        idempotency_key=str(idempotency_key),
    )


# ---------------------------------------------------------------------------
# Stub tool classes
# ---------------------------------------------------------------------------

class WarrantyClaimTool(BaseTool):
    name: ClassVar[str] = "warranty.claim"
    capability: ClassVar[ToolCapability] = ToolCapability.ACTION
    required_capabilities: ClassVar[frozenset[str]] = frozenset({"tool.warranty.claim"})

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
    ) -> ToolInvocationResult:
        try:
            payload = WarrantyClaimPayload.model_validate(request.payload)
        except ValidationError as exc:
            return _invalid_payload_result(exc)
        tenant_id = _tenant_id_for(context)
        session_id = _session_id_for(request, context)
        if tenant_id is None or session_id is None:
            return _invalid_context_result("warranty.claim requires tenant_id and session_id")
        target_resource = _target_resource_for(
            request, f"order:{payload.order_id}:sku:{payload.product_sku}"
        )
        idempotency_key = derive_action_idempotency_key(
            tenant_id=tenant_id,
            session_id=session_id,
            tool_name=self.name,
            target_resource=target_resource,
        )
        return _stub_success_result(
            tool_name=self.name,
            idempotency_key=idempotency_key,
            result_summary=f"Warranty claim submitted for order {payload.order_id} (stub)",
            metadata={
                "order_id": payload.order_id,
                "product_sku": payload.product_sku,
                "issue_category": payload.issue_category,
                "target_resource": target_resource,
            },
        )


class RefundRequestTool(BaseTool):
    name: ClassVar[str] = "refund.request"
    capability: ClassVar[ToolCapability] = ToolCapability.ACTION
    required_capabilities: ClassVar[frozenset[str]] = frozenset({"tool.refund.request"})

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
    ) -> ToolInvocationResult:
        try:
            payload = RefundRequestPayload.model_validate(request.payload)
        except ValidationError as exc:
            return _invalid_payload_result(exc)
        tenant_id = _tenant_id_for(context)
        session_id = _session_id_for(request, context)
        if tenant_id is None or session_id is None:
            return _invalid_context_result("refund.request requires tenant_id and session_id")
        target_resource = _target_resource_for(
            request, f"order:{payload.order_id}:sku:{payload.product_sku}"
        )
        idempotency_key = derive_action_idempotency_key(
            tenant_id=tenant_id,
            session_id=session_id,
            tool_name=self.name,
            target_resource=target_resource,
        )
        return _stub_success_result(
            tool_name=self.name,
            idempotency_key=idempotency_key,
            result_summary=f"Refund request prepared for order {payload.order_id} (stub)",
            metadata={
                "order_id": payload.order_id,
                "product_sku": payload.product_sku,
                "refund_amount_cents": payload.refund_amount_cents,
                "refund_reason": payload.refund_reason,
                "target_resource": target_resource,
            },
        )


class ReplacementOrderTool(BaseTool):
    name: ClassVar[str] = "replacement.order"
    capability: ClassVar[ToolCapability] = ToolCapability.ACTION
    required_capabilities: ClassVar[frozenset[str]] = frozenset({"tool.replacement.order"})

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
    ) -> ToolInvocationResult:
        try:
            payload = ReplacementOrderPayload.model_validate(request.payload)
        except ValidationError as exc:
            return _invalid_payload_result(exc)
        tenant_id = _tenant_id_for(context)
        session_id = _session_id_for(request, context)
        if tenant_id is None or session_id is None:
            return _invalid_context_result("replacement.order requires tenant_id and session_id")
        target_resource = _target_resource_for(
            request, f"order:{payload.order_id}:sku:{payload.product_sku}"
        )
        idempotency_key = derive_action_idempotency_key(
            tenant_id=tenant_id,
            session_id=session_id,
            tool_name=self.name,
            target_resource=target_resource,
        )
        return _stub_success_result(
            tool_name=self.name,
            idempotency_key=idempotency_key,
            result_summary=f"Replacement order prepared for order {payload.order_id} (stub)",
            metadata={
                "order_id": payload.order_id,
                "product_sku": payload.product_sku,
                "replacement_reason": payload.replacement_reason,
                "shipping_address_hash": payload.shipping_address_hash,
                "target_resource": target_resource,
            },
        )


class WarehouseRepairReportTool(BaseTool):
    name: ClassVar[str] = "warehouse.repair.report"
    capability: ClassVar[ToolCapability] = ToolCapability.ACTION
    required_capabilities: ClassVar[frozenset[str]] = frozenset({"tool.warehouse.repair"})

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
    ) -> ToolInvocationResult:
        try:
            payload = WarehouseRepairReportPayload.model_validate(request.payload)
        except ValidationError as exc:
            return _invalid_payload_result(exc)
        tenant_id = _tenant_id_for(context)
        session_id = _session_id_for(request, context, fallback=payload.session_id)
        if tenant_id is None or session_id is None:
            return _invalid_context_result(
                "warehouse.repair.report requires tenant_id and session_id"
            )
        batch = payload.batch_id or "unknown"
        target_resource = _target_resource_for(
            request, f"sku:{payload.product_sku}:batch:{batch}"
        )
        idempotency_key = derive_action_idempotency_key(
            tenant_id=tenant_id,
            session_id=session_id,
            tool_name=self.name,
            target_resource=target_resource,
        )
        return _stub_success_result(
            tool_name=self.name,
            idempotency_key=idempotency_key,
            result_summary=f"Warehouse repair report prepared for {payload.product_sku} (stub)",
            metadata={
                "product_sku": payload.product_sku,
                "batch_id": payload.batch_id,
                "severity": payload.severity,
                "target_resource": target_resource,
            },
        )


def build_action_tool_registry() -> "ToolRegistry":
    """Build a ToolRegistry pre-populated with stub tool instances.

    For use ONLY in direct-construction tests that need a ToolRegistry
    without a DB-backed ConnectorConfigRecord. Never called by production code.
    """
    from app.agents.tools.registry import ToolRegistry as _ToolRegistry
    registry = _ToolRegistry()
    for tool_cls in (RefundRequestTool, ReplacementOrderTool, WarehouseRepairReportTool, WarrantyClaimTool):
        registry.register(tool_cls())
    return registry


# Re-export ToolRegistry type for type annotations in calling test modules
from app.agents.tools.registry import ToolRegistry  # noqa: E402


__all__ = [
    "RefundRequestTool",
    "ReplacementOrderTool",
    "ToolRegistry",
    "WarehouseRepairReportTool",
    "WarrantyClaimTool",
    "build_action_tool_registry",
]
