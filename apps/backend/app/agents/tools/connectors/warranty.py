"""Generic REST warranty claim connector."""

from __future__ import annotations

from typing import ClassVar

from app.agents.tools.connectors.base import (
    ConnectorHTTPRequest,
    ConnectorHTTPResponse,
    ConnectorProviderFields,
    ConnectorTool,
)
from app.agents.tools.connectors.config import ConnectorConfigRecord
from app.agents.tools.connectors.refund import (
    mapped_body,
    parse_generic_rest_response,
    render_endpoint,
)
from app.types.json import JsonObject


class WarrantyClaimConnector(ConnectorTool):
    """Execute a warranty claim through a tenant-configured generic REST endpoint."""

    name: ClassVar[str] = "warranty.claim"
    required_capabilities: ClassVar[frozenset[str]] = frozenset(
        {"tool.warranty.claim"}
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
        return parse_generic_rest_response(response, config=config)


GenericRestWarrantyClaimConnector = WarrantyClaimConnector


__all__ = [
    "GenericRestWarrantyClaimConnector",
    "WarrantyClaimConnector",
]
