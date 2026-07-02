"""Base class for governed tenant action connectors."""

from __future__ import annotations

import asyncio
import logging
import ssl
from abc import abstractmethod
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from typing import Any, ClassVar, Protocol

logger = logging.getLogger(__name__)

from app.agents.context import AgentExecutionContext
from app.agents.results import ToolInvocationRequest, ToolInvocationResult
from app.agents.tools.base import BaseTool
from app.agents.tools.capability import ToolCapability
from app.agents.tools.connectors.config import (
    ConnectorConfigError,
    ConnectorConfigRecord,
    ConnectorConfigRepository,
)
from app.agents.tools.grants import AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY
from app.core.http import create_isolated_http_client
from app.core.ssrf import (
    PinnedIPAsyncHTTPTransport,
    ValidatedPublicHTTPSURL,
    validate_public_https_url,
)
from app.tenant.enums import TenantChannelType
from app.types.json import JsonObject

_DEFAULT_TIMEOUT_SECONDS = 10.0


class TenantCredentialRuntime(Protocol):
    async def load_channel_credentials(
        self,
        *,
        tenant_id: str,
        channel_type: TenantChannelType,
    ) -> dict[str, Any]: ...


class SSRFValidator(Protocol):
    def __call__(
        self,
        url: str,
        *,
        allowed_hosts: tuple[str, ...] = (),
    ) -> ValidatedPublicHTTPSURL: ...


class ConnectorHTTPResponse(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...

    def json(self) -> Any: ...


def _empty_headers() -> dict[str, str]:
    return {}


@dataclass(frozen=True, slots=True)
class ConnectorHTTPRequest:
    method: str
    url: str
    json_body: JsonObject
    headers: Mapping[str, str] = field(default_factory=_empty_headers)
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class ConnectorProviderFields:
    provider_id: str | None
    provider_status: str | None
    provider_error: str | None = None


class ConnectorResponseError(RuntimeError):
    """Provider responded, but not with a configured success outcome."""

    def __init__(
        self,
        *,
        status_code: int,
        provider_fields: ConnectorProviderFields,
    ) -> None:
        self.status_code = status_code
        self.provider_fields = provider_fields
        super().__init__(
            provider_fields.provider_error or f"http_status_{status_code}"
        )


class ConnectorTool(BaseTool):
    """BaseTool subclass that owns config, credentials, SSRF, and idempotency."""

    capability: ClassVar[ToolCapability] = ToolCapability.ACTION

    def __init__(
        self,
        *,
        config_repository: ConnectorConfigRepository,
        credential_runtime: TenantCredentialRuntime,
        ssl_context: ssl.SSLContext | None = None,
        ssrf_validator: SSRFValidator | None = None,
    ) -> None:
        self._config_repository = config_repository
        self._credential_runtime = credential_runtime
        self._ssl_context = ssl_context
        self._ssrf_validator = ssrf_validator or validate_public_https_url

    async def invoke(
        self,
        request: ToolInvocationRequest,
        context: AgentExecutionContext,
    ) -> ToolInvocationResult:
        tenant_id = _clean_text(context.tenant_id)
        if tenant_id is None:
            return _error_result(
                code="missing_tenant",
                message="connector invocation requires tenant_id",
            )
        provider_key = _clean_text(
            request.metadata.get(AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY)
        )
        if provider_key is None:
            return _error_result(
                code="missing_provider_idempotency_key",
                message="connector invocation requires provider idempotency key",
            )

        try:
            config = await self._load_config(tenant_id=tenant_id)
        except ConnectorConfigError as exc:
            return _error_result(
                code="connector_config_missing",
                message=str(exc),
                idempotency_key=provider_key,
            )
        channel_type = _channel_type(config.connector_type)
        if channel_type is None:
            return _error_result(
                code="invalid_connector_type",
                message="connector_type must map to a tenant channel type",
                idempotency_key=provider_key,
            )
        try:
            credentials = await self._credential_runtime.load_channel_credentials(
                tenant_id=tenant_id,
                channel_type=channel_type,
            )
        except Exception as exc:  # noqa: BLE001 - fail closed on credential errors.
            # Log the full exception server-side for debugging; never include
            # the body in the caller-visible message because str(exc) for a
            # credential load failure may echo a bearer token or API key.
            logger.error(
                "connector_credential_load_failed",
                extra={"tenant_id": tenant_id, "tool": self.name},
                exc_info=True,
            )
            return _error_result(
                code="credential_load_failed",
                message=f"{type(exc).__name__}: credential load failed",
                idempotency_key=provider_key,
            )
        outbound = self.build_request(
            payload=dict(request.payload),
            config=config,
        )
        headers = {
            **_auth_headers(credentials),
            **dict(outbound.headers),
            config.idempotency_header_name: provider_key,
            "Content-Type": "application/json",
        }

        validated = await _validate_url_off_loop(
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
                return _error_result(
                    code="provider_transport_error",
                    message=f"{type(exc).__name__}: provider transport error",
                    idempotency_key=provider_key,
                )

        try:
            fields = self.parse_response(response, config=config)
        except ConnectorResponseError as exc:
            return _provider_error_result(
                provider_fields=exc.provider_fields,
                message=str(exc),
                idempotency_key=provider_key,
            )
        except Exception as exc:  # noqa: BLE001 - fail closed on parse errors.
            return _error_result(
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

    @abstractmethod
    def build_request(
        self,
        *,
        payload: JsonObject,
        config: ConnectorConfigRecord,
    ) -> ConnectorHTTPRequest:
        """Build the provider request shape from governed payload + config."""

    @abstractmethod
    def parse_response(
        self,
        response: ConnectorHTTPResponse,
        *,
        config: ConnectorConfigRecord,
    ) -> ConnectorProviderFields:
        """Extract provider fields from the provider response."""

    async def _load_config(self, *, tenant_id: str) -> ConnectorConfigRecord:
        config = await self._config_repository.get_active_config(
            tenant_id=tenant_id,
            tool_name=self.name,
            expected_tenant_id=tenant_id,
        )
        if config is None:
            raise ConnectorConfigError(
                f"active connector config not found for tool {self.name!r}"
            )
        return config


def _auth_headers(credentials: Mapping[str, Any]) -> dict[str, str]:
    auth_header = _clean_text(credentials.get("auth_header")) or _clean_text(
        credentials.get("authorization")
    )
    if auth_header is not None:
        return {"Authorization": auth_header}
    bearer_token = _clean_text(credentials.get("bearer_token")) or _clean_text(
        credentials.get("access_token")
    )
    if bearer_token is not None:
        return {"Authorization": f"Bearer {bearer_token}"}
    api_key = _clean_text(credentials.get("api_key"))
    if api_key is not None:
        return {"X-API-Key": api_key}
    return {}


async def validate_connector_endpoint_url(
    *,
    validator: SSRFValidator,
    url: str,
    allowed_hosts: tuple[str, ...],
) -> ValidatedPublicHTTPSURL:
    loop = asyncio.get_running_loop()
    call = partial(validator, url, allowed_hosts=allowed_hosts)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="connector-ssrf") as pool:
        return await loop.run_in_executor(pool, call)


async def _validate_url_off_loop(
    *,
    validator: SSRFValidator,
    url: str,
    allowed_hosts: tuple[str, ...],
) -> ValidatedPublicHTTPSURL:
    return await validate_connector_endpoint_url(
        validator=validator,
        url=url,
        allowed_hosts=allowed_hosts,
    )


def _channel_type(value: str) -> TenantChannelType | None:
    try:
        return TenantChannelType(value)
    except ValueError:
        return None


def _error_result(
    *,
    code: str,
    message: str,
    idempotency_key: str | None = None,
) -> ToolInvocationResult:
    return ToolInvocationResult(
        output={"status": "error", "error_code": code},
        status="error",
        error_code=code,
        error_message=message,
        idempotency_key=idempotency_key,
    )


def _provider_error_result(
    *,
    provider_fields: ConnectorProviderFields,
    message: str,
    idempotency_key: str,
) -> ToolInvocationResult:
    return ToolInvocationResult(
        output={
            "status": "error",
            "provider_id": provider_fields.provider_id,
            "provider_status": provider_fields.provider_status,
            "provider_error": message,
        },
        status="error",
        error_code="provider_error",
        error_message=message,
        idempotency_key=idempotency_key,
    )


def _clean_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


connector_auth_headers = _auth_headers
connector_clean_text = _clean_text
connector_error_result = _error_result
connector_provider_error_result = _provider_error_result


__all__ = [
    "ConnectorHTTPResponse",
    "ConnectorHTTPRequest",
    "ConnectorProviderFields",
    "ConnectorResponseError",
    "ConnectorTool",
    "SSRFValidator",
    "TenantCredentialRuntime",
    "connector_auth_headers",
    "connector_clean_text",
    "connector_error_result",
    "connector_provider_error_result",
    "validate_connector_endpoint_url",
]
