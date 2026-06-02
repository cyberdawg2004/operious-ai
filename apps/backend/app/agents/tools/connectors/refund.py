"""Generic REST refund connector."""

from __future__ import annotations

from collections.abc import Mapping
from string import Formatter
from typing import Any, ClassVar, cast

from app.agents.tools.connectors.base import (
    ConnectorHTTPResponse,
    ConnectorHTTPRequest,
    ConnectorProviderFields,
    ConnectorTool,
)
from app.agents.tools.connectors.config import ConnectorConfigRecord
from app.types.json import JsonObject


class GenericRestRefundConnector(ConnectorTool):
    """Execute a refund through a tenant-configured generic REST endpoint."""

    name: ClassVar[str] = "refund.request"
    required_capabilities: ClassVar[frozenset[str]] = frozenset(
        {"tool.refund.request"}
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
        provider_id = _text_at(body, _parse_path(config, "provider_id"))
        provider_status = _text_at(body, _parse_path(config, "provider_status"))
        provider_error = _text_at(body, _parse_path(config, "provider_error"))
        return ConnectorProviderFields(
            provider_id=provider_id,
            provider_status=provider_status,
            provider_error=provider_error,
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


__all__ = ["GenericRestRefundConnector"]
