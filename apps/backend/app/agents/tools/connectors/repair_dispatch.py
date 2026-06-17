"""Generic REST repair-dispatch connector."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from string import Formatter
from typing import Any, ClassVar, cast

from app.agents.context import AgentExecutionContext
from app.agents.results import ToolInvocationRequest, ToolInvocationResult
from app.agents.tools.connectors.base import (
    ConnectorHTTPResponse,
    ConnectorHTTPRequest,
    ConnectorProviderFields,
    ConnectorResponseError,
    ConnectorTool,
)
from app.agents.tools.connectors.config import (
    ConnectorConfigError,
    ConnectorConfigRecord,
)
from app.agents.tools.grants import AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY
from app.types.json import JsonObject
from app.work_orders.enums import WorkOrderState
from app.work_orders.identity import derive_work_order_id
from app.work_orders.persistence.records import WorkOrderRecord
from app.work_orders.persistence.repository import WorkOrderRepositoryProtocol


class GenericRestRepairDispatchConnector(ConnectorTool):
    """Dispatch a repair work order through a tenant-configured REST endpoint."""

    name: ClassVar[str] = "repair.dispatch"
    required_capabilities: ClassVar[frozenset[str]] = frozenset(
        {"tool.repair.dispatch"}
    )

    def __init__(
        self,
        *,
        work_order_repository: WorkOrderRepositoryProtocol,
        now: Callable[[], datetime] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._work_orders = work_order_repository
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
    ) -> ToolInvocationResult:
        tenant_id = _clean_text(context.tenant_id)
        if tenant_id is None:
            return _error_result(
                code="missing_tenant",
                message="repair.dispatch requires tenant_id",
            )
        provider_key = _clean_text(
            request.metadata.get(AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY)
        )
        if provider_key is None:
            return _error_result(
                code="missing_provider_idempotency_key",
                message="repair.dispatch requires provider idempotency key",
            )
        try:
            config = await self._load_config(tenant_id=tenant_id)
        except ConnectorConfigError as exc:
            return _error_result(
                code="connector_config_missing",
                message=str(exc),
                idempotency_key=provider_key,
            )

        work_order = await self._reserve_work_order(
            tenant_id=tenant_id,
            request=request,
            context=context,
            config=config,
            idempotency_key=provider_key,
        )
        if work_order.state is WorkOrderState.AWAITING_FULFILLMENT:
            return _success_result(
                idempotency_key=provider_key,
                work_order_id=str(work_order.work_order_id),
                provider_work_order_id=work_order.provider_work_order_id,
                provider_status=work_order.provider_status,
                replayed=True,
            )
        if work_order.state is WorkOrderState.FAILED:
            return _error_result(
                code="work_order_dispatch_previously_failed",
                message="repair.dispatch previously failed for this idempotency key",
                idempotency_key=provider_key,
                work_order_id=str(work_order.work_order_id),
                provider_work_order_id=work_order.provider_work_order_id,
                provider_status=work_order.provider_status,
            )

        try:
            result = await super().invoke(request, context)
        except Exception as exc:  # noqa: BLE001 - tool returns typed result.
            failed = await self._transition_failed(
                work_order,
                provider_status="tool_raised",
                provider_error=f"{type(exc).__name__}: {exc}",
            )
            return _error_result(
                code="dispatch_failed",
                message=f"{type(exc).__name__}: {exc}",
                idempotency_key=provider_key,
                work_order_id=str(failed.work_order_id),
                provider_work_order_id=failed.provider_work_order_id,
                provider_status=failed.provider_status,
            )

        if result.status == "success":
            provider_work_order_id = _result_text(result, "provider_id")
            provider_status = _result_text(result, "provider_status") or "accepted"
            dispatched = await self._work_orders.transition_work_order(
                work_order.work_order_id,
                to_state=WorkOrderState.DISPATCHED,
                transitioned_at=self._now(),
                expected_tenant_id=tenant_id,
                provider_work_order_id=provider_work_order_id,
                provider_status=provider_status,
                metadata={"tool": self.name, "phase": "dispatch_accepted"},
            )
            awaiting = await self._work_orders.transition_work_order(
                dispatched.work_order_id,
                to_state=WorkOrderState.AWAITING_FULFILLMENT,
                transitioned_at=self._now(),
                expected_tenant_id=tenant_id,
                provider_work_order_id=provider_work_order_id,
                provider_status=provider_status,
                metadata={
                    "tool": self.name,
                    "phase": "awaiting_tenant_fulfillment",
                },
            )
            return ToolInvocationResult(
                output={
                    **dict(result.output),
                    "provider_work_order_id": provider_work_order_id,
                    "work_order_id": str(awaiting.work_order_id),
                    "work_order_state": awaiting.state.value,
                },
                metadata={
                    **dict(result.metadata),
                    "work_order_id": str(awaiting.work_order_id),
                    "work_order_state": awaiting.state.value,
                    "connector_config_version": config.version,
                    "connector_config_content_sha256": config.content_sha256,
                    "connector_config_source_approval_id": (
                        config.source_approval_id
                    ),
                },
                status=result.status,
                error_code=result.error_code,
                error_message=result.error_message,
                idempotency_key=result.idempotency_key,
            )

        failed = await self._transition_failed(
            work_order,
            provider_status=_result_text(result, "provider_status"),
            provider_error=(
                result.error_message
                or _result_text(result, "provider_error")
                or "provider_error"
            ),
        )
        return ToolInvocationResult(
            output={
                **dict(result.output),
                "work_order_id": str(failed.work_order_id),
                "work_order_state": failed.state.value,
            },
            metadata={
                **dict(result.metadata),
                "work_order_id": str(failed.work_order_id),
                "work_order_state": failed.state.value,
            },
            status=result.status,
            error_code=result.error_code,
            error_message=result.error_message,
            idempotency_key=result.idempotency_key,
        )

    def build_request(
        self,
        *,
        payload: JsonObject,
        config: ConnectorConfigRecord,
    ) -> ConnectorHTTPRequest:
        return ConnectorHTTPRequest(
            method=config.http_method,
            url=_render_endpoint(config.endpoint_template, payload),
            json_body=_mapped_body(payload, config.field_mappings),
        )

    def parse_response(
        self,
        response: ConnectorHTTPResponse,
        *,
        config: ConnectorConfigRecord,
    ) -> ConnectorProviderFields:
        body = _response_json(response)
        provider_id = (
            _text_at(body, _parse_path(config, "provider_work_order_id"))
            or _text_at(body, _parse_path(config, "provider_id"))
        )
        provider_status = _text_at(body, _parse_path(config, "provider_status"))
        provider_error = _text_at(body, _parse_path(config, "provider_error"))
        fields = ConnectorProviderFields(
            provider_id=provider_id,
            provider_status=provider_status,
            provider_error=provider_error,
        )
        if response.status_code not in set(config.success_status_codes):
            raise ConnectorResponseError(
                status_code=response.status_code,
                provider_fields=fields,
            )
        return fields

    async def _reserve_work_order(
        self,
        *,
        tenant_id: str,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
        config: ConnectorConfigRecord,
        idempotency_key: str,
    ) -> WorkOrderRecord:
        action_type = _metadata_text(request, "action_type") or self.name
        target_resource = (
            _metadata_text(request, "target_resource")
            or _target_resource_from_payload(request.payload)
        )
        return await self._work_orders.create_work_order(
            WorkOrderRecord(
                work_order_id=derive_work_order_id(
                    tenant_id=tenant_id,
                    action_type=action_type,
                    idempotency_key=idempotency_key,
                ),
                tenant_id=tenant_id,
                session_id=_metadata_uuid(request, "session_id"),
                proposal_id=_metadata_uuid(request, "proposal_id"),
                execution_id=_metadata_uuid(request, "execution_id"),
                dispatch_id=_metadata_uuid(request, "dispatch_id"),
                action_type=action_type,
                tool_name=self.name,
                connector_type=config.connector_type,
                connector_config_version=config.version,
                connector_config_content_sha256=config.content_sha256,
                connector_config_source_approval_id=config.source_approval_id,
                idempotency_key=idempotency_key,
                target_resource=target_resource,
                metadata={
                    "agent_id": context.identity.agent_id,
                    "runtime_instance_id": str(context.identity.runtime_instance_id),
                    "execution_context_id": str(context.execution.execution_id),
                },
            ),
            expected_tenant_id=tenant_id,
        )

    async def _transition_failed(
        self,
        work_order: WorkOrderRecord,
        *,
        provider_status: str | None,
        provider_error: str,
    ) -> WorkOrderRecord:
        return await self._work_orders.transition_work_order(
            work_order.work_order_id,
            to_state=WorkOrderState.FAILED,
            transitioned_at=self._now(),
            expected_tenant_id=work_order.tenant_id,
            provider_status=provider_status or "failed",
            metadata={
                "tool": self.name,
                "phase": "dispatch_failed",
                "provider_error": provider_error,
            },
        )


def _success_result(
    *,
    idempotency_key: str,
    work_order_id: str,
    provider_work_order_id: str | None,
    provider_status: str | None,
    replayed: bool,
) -> ToolInvocationResult:
    return ToolInvocationResult(
        output={
            "status": "success",
            "provider_id": provider_work_order_id,
            "provider_work_order_id": provider_work_order_id,
            "provider_status": provider_status or "accepted",
            "work_order_id": work_order_id,
            "work_order_state": WorkOrderState.AWAITING_FULFILLMENT.value,
            "replayed": replayed,
        },
        metadata={
            "work_order_id": work_order_id,
            "work_order_state": WorkOrderState.AWAITING_FULFILLMENT.value,
            "replayed": replayed,
        },
        status="success",
        idempotency_key=idempotency_key,
    )


def _error_result(
    *,
    code: str,
    message: str,
    idempotency_key: str | None = None,
    work_order_id: str | None = None,
    provider_work_order_id: str | None = None,
    provider_status: str | None = None,
) -> ToolInvocationResult:
    output: JsonObject = {
        "status": "error",
        "error_code": code,
        "provider_id": provider_work_order_id,
        "provider_work_order_id": provider_work_order_id,
        "provider_status": provider_status,
    }
    if work_order_id is not None:
        output["work_order_id"] = work_order_id
        output["work_order_state"] = WorkOrderState.FAILED.value
    return ToolInvocationResult(
        output=output,
        metadata={k: v for k, v in output.items() if v is not None},
        status="error",
        error_code=code,
        error_message=message,
        idempotency_key=idempotency_key,
    )


def _render_endpoint(template: str, payload: Mapping[str, Any]) -> str:
    values: dict[str, str] = {}
    for _, field_name, _, _ in Formatter().parse(template):
        if field_name is None:
            continue
        values[field_name] = str(_value_at(payload, field_name) or "")
    return template.format(**values)


def _mapped_body(
    payload: Mapping[str, Any],
    mappings: Mapping[str, Any],
) -> JsonObject:
    if not mappings:
        return {str(k): v for k, v in payload.items()}
    body: JsonObject = {}
    for target, source in mappings.items():
        value = _mapping_value(payload, source)
        if value is not None:
            body[str(target)] = value
    return body


def _mapping_value(payload: Mapping[str, Any], source: object) -> Any:
    if isinstance(source, Mapping):
        source_map = cast(Mapping[str, Any], source)
        raw_source = source_map.get("source")
        if isinstance(raw_source, str):
            return _mapping_value(payload, raw_source)
        if "literal" in source_map:
            return source_map["literal"]
        return None
    if isinstance(source, str):
        if source.startswith("literal:"):
            return source[len("literal:") :]
        clean = source.removeprefix("payload.")
        return _value_at(payload, clean)
    return source


def _parse_path(config: ConnectorConfigRecord, key: str) -> str | None:
    value = config.response_parse.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _response_json(response: ConnectorHTTPResponse) -> Mapping[str, Any]:
    try:
        decoded = response.json()
    except ValueError:
        return {}
    if isinstance(decoded, Mapping):
        return cast(Mapping[str, Any], decoded)
    return {}


def _text_at(body: Mapping[str, Any], path: str | None) -> str | None:
    if path is None:
        return None
    value = _value_at(body, path)
    if isinstance(value, str) and value.strip():
        return value.strip()
    if value is not None:
        return str(value)
    return None


def _value_at(values: Mapping[str, Any], path: str) -> Any:
    current: object = values
    for part in path.split("."):
        current = _mapping_get(current, part)
        if current is None:
            return None
    return current


def _mapping_get(value: object, key: str) -> object | None:
    if not isinstance(value, Mapping):
        return None
    mapping = cast(Mapping[object, object], value)
    return mapping.get(key)


def _metadata_text(request: ToolInvocationRequest, key: str) -> str | None:
    return _clean_text(request.metadata.get(key))


def _metadata_uuid(
    request: ToolInvocationRequest,
    key: str,
) -> uuid.UUID | None:
    value = _metadata_text(request, key)
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _target_resource_from_payload(payload: Mapping[str, Any]) -> str:
    order_id = _clean_text(payload.get("order_id")) or "unknown-order"
    sku = _clean_text(payload.get("product_sku")) or "unknown-sku"
    return f"repair:{order_id}:{sku}"


def _result_text(result: ToolInvocationResult, key: str) -> str | None:
    return _clean_text(result.output.get(key))


def _clean_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = ["GenericRestRepairDispatchConnector"]
