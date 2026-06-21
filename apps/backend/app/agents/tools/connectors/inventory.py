"""Generic REST inventory-availability connector — read-only query.

Same SSRF/credential/idempotency rigor as the money-moving connectors
(refund.py/replacement.py/warranty.py) even though this connector never
mutates anything: it's still a tenant-configured external call, so it
gets connector-feature rigor. It only ever queries availability for a
SKU/remedy and reports back; it has no write path at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar, cast

from app.agents.tools.connectors.base import (
    ConnectorHTTPRequest,
    ConnectorHTTPResponse,
    ConnectorProviderFields,
    ConnectorResponseError,
    ConnectorTool,
)
from app.agents.tools.connectors.config import ConnectorConfigRecord
from app.agents.tools.connectors.refund import (
    mapped_body,
    parse_response_path,
    render_endpoint,
    response_json,
    text_at,
)
from app.types.json import JsonObject

AVAILABLE_PROVIDER_STATUS = "available"
UNAVAILABLE_PROVIDER_STATUS = "unavailable"

_TRUTHY_STRINGS = frozenset({"true", "1", "yes", "in_stock", "available"})


class InventoryCheckConnector(ConnectorTool):
    """Query availability for a SKU/remedy through a tenant-configured
    generic REST endpoint. Read-only — never mutates inventory, never
    moves goods.
    """

    name: ClassVar[str] = "inventory.check"
    required_capabilities: ClassVar[frozenset[str]] = frozenset(
        {"tool.inventory.check"}
    )

    def build_request(
        self,
        *,
        payload: JsonObject,
        config: ConnectorConfigRecord,
    ) -> ConnectorHTTPRequest:
        return ConnectorHTTPRequest(
            method=config.http_method,
            url=render_endpoint(config.endpoint_template, payload),
            json_body=mapped_body(payload, config.field_mappings),
        )

    def parse_response(
        self,
        response: ConnectorHTTPResponse,
        *,
        config: ConnectorConfigRecord,
    ) -> ConnectorProviderFields:
        body = response_json(response)
        available_path = parse_response_path(config, "available")
        fields = ConnectorProviderFields(
            provider_id=text_at(body, parse_response_path(config, "provider_id")),
            provider_status=(
                AVAILABLE_PROVIDER_STATUS
                if _is_available(_value_at(body, available_path))
                else UNAVAILABLE_PROVIDER_STATUS
            ),
            provider_error=text_at(body, parse_response_path(config, "provider_error")),
        )
        if response.status_code not in set(config.success_status_codes):
            raise ConnectorResponseError(
                status_code=response.status_code,
                provider_fields=fields,
            )
        return fields


def _is_available(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in _TRUTHY_STRINGS
    if isinstance(value, int):
        return value > 0
    return False


def _value_at(values: Mapping[str, object], path: str | None) -> object | None:
    if path is None:
        return None
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


__all__ = [
    "AVAILABLE_PROVIDER_STATUS",
    "InventoryCheckConnector",
    "UNAVAILABLE_PROVIDER_STATUS",
]
