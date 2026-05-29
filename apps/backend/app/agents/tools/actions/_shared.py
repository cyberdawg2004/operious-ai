"""Shared helpers for stub action tools."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import ValidationError

from app.agents.context import AgentExecutionContext
from app.agents.results import ToolInvocationRequest, ToolInvocationResult


def invalid_payload_result(exc: ValidationError) -> ToolInvocationResult:
    return ToolInvocationResult(
        output={
            "status": "error",
            "error_code": "invalid_payload",
        },
        status="error",
        error_code="invalid_payload",
        error_message=str(exc),
    )


def invalid_context_result(message: str) -> ToolInvocationResult:
    return ToolInvocationResult(
        output={
            "status": "error",
            "error_code": "invalid_context",
        },
        status="error",
        error_code="invalid_context",
        error_message=message,
    )


def session_id_for(
    request: ToolInvocationRequest,
    context: AgentExecutionContext,
    *,
    fallback: str | None = None,
) -> str | None:
    request_value = _text(request.metadata.get("session_id"))
    if request_value is not None:
        return request_value
    context_value = _text(context.metadata.get("session_id"))
    if context_value is not None:
        return context_value
    return fallback


def target_resource_for(
    request: ToolInvocationRequest,
    default: str,
) -> str:
    return _text(request.metadata.get("target_resource")) or default


def success_result(
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
        metadata={
            **metadata,
            "tool": tool_name,
            "stub": True,
        },
        status="success",
        idempotency_key=str(idempotency_key),
    )


def tenant_id_for(context: AgentExecutionContext) -> str | None:
    return _text(context.tenant_id)


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "invalid_context_result",
    "invalid_payload_result",
    "session_id_for",
    "success_result",
    "target_resource_for",
    "tenant_id_for",
]
