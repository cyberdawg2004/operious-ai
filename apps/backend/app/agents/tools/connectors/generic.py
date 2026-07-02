"""Generic connector + operations model.

A connector is connector_id + protocol + credential ref + network policy.
An operation is operation_id + mode(read|act) + input schema +
request/response mapping + idempotency + governance metadata.

Domain-agnostic: names no vendor, domain, or business-action in code.
"""

from __future__ import annotations

import logging
import ssl

logger = logging.getLogger(__name__)
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Protocol

from app.agents.context import AgentExecutionContext
from app.agents.results import ToolInvocationRequest, ToolInvocationResult
from app.agents.tools.base import BaseTool
from app.agents.tools.capability import ToolCapability
from app.agents.tools.connectors.base import (
    ConnectorHTTPRequest,
    ConnectorHTTPResponse,
    ConnectorProviderFields,
    ConnectorResponseError,
    SSRFValidator,
    connector_auth_headers,
    connector_clean_text,
    connector_error_result,
    connector_provider_error_result,
    validate_connector_endpoint_url,
)
from app.agents.tools.connectors.config import (
    ConnectorConfigError,
    ConnectorConfigRecord,
    ConnectorConfigRepository,
)
from app.agents.tools.connectors.refund import (
    mapped_body,
    parse_generic_rest_response,
    render_endpoint,
)
from app.agents.tools.grants import AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY
from app.agents.tools.operation_metadata import (
    APPROVAL_POLICY_METADATA_KEY,
    COMMITMENT_KIND_METADATA_KEY,
    OPERATION_ID_METADATA_KEY,
    TARGET_RESOURCE_EXPR_METADATA_KEY,
    ApprovalPolicy,
    CommitmentKind,
)
from app.core.http import create_isolated_http_client
from app.core.ssrf import (
    PinnedIPAsyncHTTPTransport,
    validate_public_https_url,
)
from app.types.json import JsonObject


class OperationMode(StrEnum):
    READ = "read"
    ACT = "act"


class IdempotencyStrategy(StrEnum):
    HEADER = "header"
    NONE = "none"


class ConnectorCredentialRuntime(Protocol):
    """Resolves credentials by connector_id — decoupled from channel enum."""

    async def load_connector_credentials(
        self,
        *,
        tenant_id: str,
        connector_id: str,
    ) -> dict[str, Any]: ...


def _empty_schema() -> dict[str, Any]:
    return {}


def _empty_mappings() -> dict[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class OperationDefinition:
    """A single operation exposed by a connector."""

    operation_id: str
    mode: OperationMode
    input_schema: Mapping[str, Any] = field(default_factory=_empty_schema)
    request_mapping: Mapping[str, Any] = field(default_factory=_empty_mappings)
    response_mapping: Mapping[str, Any] = field(default_factory=_empty_mappings)
    idempotency_strategy: IdempotencyStrategy = IdempotencyStrategy.HEADER
    commitment_kind: CommitmentKind | None = None
    approval_policy: ApprovalPolicy | None = None
    target_resource_expr: str | None = None

    def governance_metadata(self) -> JsonObject:
        metadata: JsonObject = {OPERATION_ID_METADATA_KEY: self.operation_id}
        if self.commitment_kind is not None:
            metadata[COMMITMENT_KIND_METADATA_KEY] = self.commitment_kind.value
        if self.approval_policy is not None:
            metadata[APPROVAL_POLICY_METADATA_KEY] = self.approval_policy.value
        if self.target_resource_expr is not None:
            metadata[TARGET_RESOURCE_EXPR_METADATA_KEY] = self.target_resource_expr
        return metadata

    @property
    def requires_governance(self) -> bool:
        return self.mode is OperationMode.ACT


@dataclass(frozen=True, slots=True)
class ConnectorDefinition:
    """A generic connector — connector_id + protocol + operations."""

    connector_id: str
    protocol: str
    operations: Sequence[OperationDefinition]
    network_policy: Mapping[str, Any] = field(default_factory=_empty_schema)

    def get_operation(self, operation_id: str) -> OperationDefinition | None:
        for op in self.operations:
            if op.operation_id == operation_id:
                return op
        return None


_DEFAULT_TIMEOUT_SECONDS = 10.0


class GenericConnectorTool(BaseTool):
    """Executes a declared operation on a generic connector.

    Reuses the existing transport substrate (SSRF, IP-pin, TLS,
    idempotency) and the existing governance seam (operation metadata →
    Stage-1 policy gate).
    """

    capability: ClassVar[ToolCapability] = ToolCapability.ACTION

    def __init__(
        self,
        *,
        connector: ConnectorDefinition,
        operation: OperationDefinition,
        config_repository: ConnectorConfigRepository,
        credential_runtime: ConnectorCredentialRuntime,
        ssl_context: ssl.SSLContext | None = None,
        ssrf_validator: SSRFValidator | None = None,
    ) -> None:
        self._connector = connector
        self._operation = operation
        self._config_repository = config_repository
        self._credential_runtime = credential_runtime
        self._ssl_context = ssl_context
        self._ssrf_validator = ssrf_validator or validate_public_https_url
        self._name = f"{connector.connector_id}.{operation.operation_id}"

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    @property
    def connector_definition(self) -> ConnectorDefinition:
        return self._connector

    @property
    def operation_definition(self) -> OperationDefinition:
        return self._operation

    def operation_governance_metadata(self) -> JsonObject:
        return self._operation.governance_metadata()

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
    ) -> ToolInvocationResult:
        tenant_id = connector_clean_text(context.tenant_id)
        if tenant_id is None:
            return connector_error_result(
                code="missing_tenant",
                message="connector invocation requires tenant_id",
            )

        provider_key = connector_clean_text(
            request.metadata.get(AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY)
        )
        if self._operation.idempotency_strategy is IdempotencyStrategy.HEADER:
            if provider_key is None:
                return connector_error_result(
                    code="missing_provider_idempotency_key",
                    message="connector invocation requires provider idempotency key",
                )

        try:
            config = await self._load_config(tenant_id=tenant_id)
        except ConnectorConfigError as exc:
            return connector_error_result(
                code="connector_config_missing",
                message=str(exc),
                idempotency_key=provider_key,
            )

        try:
            credentials = await self._credential_runtime.load_connector_credentials(
                tenant_id=tenant_id,
                connector_id=self._connector.connector_id,
            )
        except Exception as exc:  # noqa: BLE001 - fail closed on credential errors.
            logger.error(
                "connector_credential_load_failed",
                extra={"tenant_id": tenant_id, "connector": self._connector.connector_id},
                exc_info=True,
            )
            return connector_error_result(
                code="credential_load_failed",
                message=f"{type(exc).__name__}: credential load failed",
                idempotency_key=provider_key,
            )

        payload = dict(request.payload)
        outbound = self._build_request(payload=payload, config=config)
        headers: dict[str, str] = {
            **connector_auth_headers(credentials),
            **dict(outbound.headers),
            "Content-Type": "application/json",
        }
        if (
            self._operation.idempotency_strategy is IdempotencyStrategy.HEADER
            and provider_key is not None
        ):
            headers[config.idempotency_header_name] = provider_key

        validated = await validate_connector_endpoint_url(
            validator=self._ssrf_validator,
            url=outbound.url,
            allowed_hosts=(config.endpoint_host.lower(),),
        )
        transport = PinnedIPAsyncHTTPTransport(
            pinned_ip=validated.pinned_ip,
            ssl_context=self._ssl_context,
        )
        async with create_isolated_http_client(
            transport=transport,
            timeout_seconds=outbound.timeout_seconds,
            follow_redirects=False,
        ) as client:
            try:
                response = await client.request(
                    outbound.method.upper(),
                    validated.url,
                    json=outbound.json_body,
                    headers=headers,
                    timeout=outbound.timeout_seconds,
                    follow_redirects=False,
                )
            except Exception as exc:  # noqa: BLE001 - fail closed on transport errors.
                return connector_error_result(
                    code="provider_transport_error",
                    message=f"{type(exc).__name__}: provider transport error",
                    idempotency_key=provider_key,
                )

        try:
            fields = self._parse_response(response, config=config)
        except ConnectorResponseError as exc:
            return connector_provider_error_result(
                provider_fields=exc.provider_fields,
                message=str(exc),
                idempotency_key=provider_key or "",
            )
        except Exception as exc:  # noqa: BLE001 - fail closed on parse errors.
            return connector_error_result(
                code="provider_response_parse_error",
                message=f"{type(exc).__name__}: provider response parse error",
                idempotency_key=provider_key,
            )

        return ToolInvocationResult(
            output={
                "status": "success",
                "provider_id": fields.provider_id,
                "provider_status": fields.provider_status or "success",
            },
            status="success",
            idempotency_key=provider_key,
        )

    def _build_request(
        self,
        *,
        payload: JsonObject,
        config: ConnectorConfigRecord,
    ) -> ConnectorHTTPRequest:
        field_mappings = (
            dict(self._operation.request_mapping)
            if self._operation.request_mapping
            else dict(config.field_mappings)
        )
        return ConnectorHTTPRequest(
            method=config.http_method,
            url=render_endpoint(config.endpoint_template, payload),
            json_body=mapped_body(payload, field_mappings),
        )

    def _parse_response(
        self,
        response: ConnectorHTTPResponse,
        *,
        config: ConnectorConfigRecord,
    ) -> ConnectorProviderFields:
        return parse_generic_rest_response(response, config=config)

    async def _load_config(self, *, tenant_id: str) -> ConnectorConfigRecord:
        config = await self._config_repository.get_active_config(
            tenant_id=tenant_id,
            tool_name=self._name,
            expected_tenant_id=tenant_id,
        )
        if config is None:
            raise ConnectorConfigError(
                f"active connector config not found for tool {self._name!r}"
            )
        return config


def validate_connector_definition(definition: ConnectorDefinition) -> list[str]:
    """Validate a connector definition for correctness.

    Returns a list of validation errors (empty = valid).
    """
    errors: list[str] = []
    if not definition.connector_id or not definition.connector_id.strip():
        errors.append("connector_id is required")
    if not definition.protocol or not definition.protocol.strip():
        errors.append("protocol is required")
    if not definition.operations:
        errors.append("at least one operation is required")

    seen_ids: set[str] = set()
    for op in definition.operations:
        if not op.operation_id or not op.operation_id.strip():
            errors.append("operation_id is required for each operation")
            continue
        if op.operation_id in seen_ids:
            errors.append(f"duplicate operation_id: {op.operation_id}")
        seen_ids.add(op.operation_id)

        if op.mode is OperationMode.ACT and op.commitment_kind is None:
            errors.append(
                f"act operation {op.operation_id!r} must declare commitment_kind"
            )

    return errors


def fail_closed_governance_check(operation: OperationDefinition) -> bool:
    """Return True if this operation must route to human approval.

    Fail-closed: an act operation with missing or unknown commitment_kind
    always requires human review.
    """
    if operation.mode is not OperationMode.ACT:
        return False
    if operation.commitment_kind is None:
        return True
    return False


class ChannelBridgedConnectorCredentialRuntime:
    """Adapter: resolves connector credentials via the existing channel
    credential infrastructure, using a connector-scoped channel_type string.

    Credential storage reuses OPCRED2 AES-GCM with AAD bound to
    "connector:{connector_id}" — encrypted, write-only, never in config.
    """

    def __init__(
        self,
        *,
        channel_credential_loader: Any,
        connector_channel_map: Mapping[str, Any],
    ) -> None:
        self._loader = channel_credential_loader
        self._map = connector_channel_map

    async def load_connector_credentials(
        self,
        *,
        tenant_id: str,
        connector_id: str,
    ) -> dict[str, Any]:
        channel_type = self._map.get(connector_id)
        if channel_type is None:
            raise ConnectorConfigError(
                f"no credential binding for connector {connector_id!r}"
            )
        return await self._loader.load_channel_credentials(
            tenant_id=tenant_id,
            channel_type=channel_type,
        )


__all__ = [
    "ChannelBridgedConnectorCredentialRuntime",
    "ConnectorCredentialRuntime",
    "ConnectorDefinition",
    "GenericConnectorTool",
    "IdempotencyStrategy",
    "OperationDefinition",
    "OperationMode",
    "fail_closed_governance_check",
    "validate_connector_definition",
]
