"""Phase 2.3 connector framework break-control tests."""

from __future__ import annotations

import asyncio
import os
import ssl
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import (
    AgentCapability,
    CapabilitySet,
    ExecutionConstraints,
)
from app.agents.context import AgentExecutionContext
from app.agents.enums import CapabilityScope
from app.agents.identity import AgentIdentity, ExecutionIdentity
from app.agents.results import ToolInvocationRequest
from app.agents.tools import ToolInvoker, ToolRegistry
from app.agents.tools.action_governance import build_action_tool_governance_runtime
from app.agents.tools.actions import (
    RefundRequestTool,
    build_tenant_action_tool_registry,
)
from app.agents.tools.connectors import (
    ConnectorConfigRecord,
    GenericRestRefundConnector,
    InMemoryConnectorConfigRepository,
    PostgresConnectorConfigRepository,
)
from app.agents.tools.grants import AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY
from app.agents.value_objects import CausalityMetadata
from app.core.ssrf import (
    SSRFValidationError,
    ValidatedPublicHTTPSURL,
    validate_public_https_url,
)
from app.governance.persistence.memory import InMemoryGovernanceRepository
from app.tenant.enums import TenantChannelType
from tests.conftest import requires_postgres

TENANT_ID = "tenant-connector"
TOOL_NAME = "refund.request"
PROVIDER_KEY = "provider-key-2-3"
SECRET = "super-secret-refund-token"


class _CredentialRuntime:
    def __init__(self) -> None:
        self.calls = 0

    async def load_channel_credentials(
        self,
        *,
        tenant_id: str,
        channel_type: TenantChannelType,
    ) -> dict[str, Any]:
        self.calls += 1
        assert tenant_id == TENANT_ID
        assert channel_type is TenantChannelType.ZENDESK
        return {"auth_header": f"Bearer {SECRET}"}


@pytest.mark.asyncio
async def test_private_provider_ip_is_rejected_before_network() -> None:
    credentials = _CredentialRuntime()
    connector = GenericRestRefundConnector(
        config_repository=await _memory_config(
            endpoint_template="https://refund.example/refunds",
            endpoint_host="refund.example",
        ),
        credential_runtime=credentials,
        ssrf_validator=_private_ip_validator,
    )
    with pytest.raises(SSRFValidationError):
        await connector.invoke(_refund_request(), _context())


@pytest.mark.asyncio
async def test_provider_idempotency_header_reaches_real_socket(
    tmp_path: Path,
) -> None:
    hostname = "refund.local"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, hostname)
    server = await _start_refund_server_or_skip(
        cert_path=cert_path,
        key_path=key_path,
    )
    client_context = ssl.create_default_context(cafile=cert_path)
    client_context.check_hostname = True
    connector = GenericRestRefundConnector(
        config_repository=await _memory_config(
            endpoint_template=(
                f"https://{hostname}:{_server_port(server.server)}/refunds"
            ),
            endpoint_host=hostname,
        ),
        credential_runtime=_CredentialRuntime(),
        ssl_context=client_context,
        ssrf_validator=_local_validator,
    )

    try:
        first = await _invoke_socket_or_skip(
            connector.invoke(_refund_request(), _context())
        )
        second = await _invoke_socket_or_skip(
            connector.invoke(_refund_request(), _context())
        )
    finally:
        await _close_server(server.server)

    assert first.status == "success"
    assert second.status == "success"
    assert server.idempotency_headers == [PROVIDER_KEY, PROVIDER_KEY]
    assert server.effect_count == 1


@pytest.mark.asyncio
async def test_credentials_not_logged_or_returned(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    hostname = "refund-secret.local"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, hostname)
    server = await _start_refund_server_or_skip(
        cert_path=cert_path,
        key_path=key_path,
    )
    client_context = ssl.create_default_context(cafile=cert_path)
    connector = GenericRestRefundConnector(
        config_repository=await _memory_config(
            endpoint_template=(
                f"https://{hostname}:{_server_port(server.server)}/refunds"
            ),
            endpoint_host=hostname,
        ),
        credential_runtime=_CredentialRuntime(),
        ssl_context=client_context,
        ssrf_validator=_local_validator,
    )

    try:
        result = await _invoke_socket_or_skip(
            connector.invoke(_refund_request(), _context())
        )
    finally:
        await _close_server(server.server)

    assert result.status == "success"
    assert server.authorization_headers == [f"Bearer {SECRET}"]
    assert SECRET not in caplog.text
    assert SECRET not in str(result.output)
    assert SECRET not in str(result.metadata)


@pytest.mark.asyncio
async def test_governance_gate_blocks_connector_without_allow() -> None:
    credentials = _CredentialRuntime()
    registry = ToolRegistry()
    registry.register(
        GenericRestRefundConnector(
            config_repository=await _memory_config(
                endpoint_template="https://refund.example/refunds",
                endpoint_host="refund.example",
            ),
            credential_runtime=credentials,
            ssrf_validator=_private_ip_validator,
        )
    )

    envelope = await ToolInvoker(
        tool_registry=registry,
        governance_runtime=build_action_tool_governance_runtime(
            persistence=InMemoryGovernanceRepository(),
            redis_client=None,
        ),
    ).invoke(
        _refund_request(refund_amount_cents=999999),
        _context(),
        invocation_ordinal=1,
    )

    assert envelope.is_denied
    assert credentials.calls == 0


@pytest.mark.asyncio
@requires_postgres
async def test_connector_config_queryable_without_decrypting_credentials(
    pg_session: AsyncSession,
) -> None:
    repository = PostgresConnectorConfigRepository(pg_session)
    record = _config(
        endpoint_template="https://refund.example/refunds",
        endpoint_host="refund.example",
    )

    await repository.save_config(record, expected_tenant_id=TENANT_ID)
    loaded = await repository.get_active_config(
        tenant_id=TENANT_ID,
        tool_name=TOOL_NAME,
        expected_tenant_id=TENANT_ID,
    )

    assert loaded is not None
    assert loaded.endpoint_template == "https://refund.example/refunds"
    assert loaded.field_mappings["order_id"] == "payload.order_id"
    assert SECRET not in str(loaded)


@pytest.mark.asyncio
async def test_unconfigured_tenant_keeps_refund_stub() -> None:
    registry = await build_tenant_action_tool_registry(
        tenant_id=TENANT_ID,
        config_repository=InMemoryConnectorConfigRepository(),
        credential_runtime=_CredentialRuntime(),
    )

    assert isinstance(registry.get(TOOL_NAME), RefundRequestTool)


async def _memory_config(
    *,
    endpoint_template: str,
    endpoint_host: str,
) -> InMemoryConnectorConfigRepository:
    repository = InMemoryConnectorConfigRepository()
    await repository.save_config(
        _config(
            endpoint_template=endpoint_template,
            endpoint_host=endpoint_host,
        ),
        expected_tenant_id=TENANT_ID,
    )
    return repository


def _config(
    *,
    endpoint_template: str,
    endpoint_host: str,
) -> ConnectorConfigRecord:
    return ConnectorConfigRecord(
        tenant_id=TENANT_ID,
        connector_type=TenantChannelType.ZENDESK.value,
        tool_name=TOOL_NAME,
        http_method="POST",
        endpoint_template=endpoint_template,
        endpoint_host=endpoint_host,
        field_mappings={
            "order_id": "payload.order_id",
            "sku": "payload.product_sku",
            "amount_cents": "payload.refund_amount_cents",
            "reason": "payload.refund_reason",
        },
        idempotency_header_name="X-Idempotency-Key",
        response_parse={
            "provider_id": "refund.id",
            "provider_status": "refund.status",
            "provider_error": "error.message",
        },
        success_status_codes=(200, 201, 202),
    )


def _refund_request(
    *,
    refund_amount_cents: int = 1299,
) -> ToolInvocationRequest:
    return ToolInvocationRequest(
        tool_name=TOOL_NAME,
        payload={
            "order_id": "order-1",
            "product_sku": "sku-1",
            "refund_amount_cents": refund_amount_cents,
            "refund_reason": "defective",
        },
        metadata={
            "session_id": "session-connector",
            "target_resource": "order:order-1:sku:sku-1",
            "tool_name": TOOL_NAME,
            "refund_amount_cents": refund_amount_cents,
            AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY: PROVIDER_KEY,
        },
    )


def _context() -> AgentExecutionContext:
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="test-refund-agent",
            runtime_instance_id=uuid.uuid5(uuid.NAMESPACE_URL, "refund-agent"),
        ),
        execution=ExecutionIdentity(
            execution_id=uuid.uuid5(uuid.NAMESPACE_URL, "refund-exec"),
            request_id="refund-request",
        ),
        capabilities=CapabilitySet(
            (
                AgentCapability(
                    name="tool.refund.request",
                    scope=CapabilityScope.INVOKE,
                ),
            )
        ),
        constraints=ExecutionConstraints(),
        causality=CausalityMetadata(),
        tenant_id=TENANT_ID,
        metadata={"session_id": "session-connector"},
    )


def _private_ip_validator(
    url: str,
    *,
    allowed_hosts: tuple[str, ...] = (),
) -> ValidatedPublicHTTPSURL:
    def _resolve(_host: str, _port: int) -> tuple[str, ...]:
        return ("169.254.169.254",)

    return validate_public_https_url(
        url,
        allowed_hosts=allowed_hosts,
        resolve=_resolve,
    )


def _local_validator(
    url: str,
    *,
    allowed_hosts: tuple[str, ...] = (),
) -> ValidatedPublicHTTPSURL:
    parsed = urlsplit(url)
    assert parsed.hostname in allowed_hosts
    return ValidatedPublicHTTPSURL(
        url=url,
        hostname=parsed.hostname or "",
        port=parsed.port or 443,
        pinned_ip="127.0.0.1",
    )


@dataclass(slots=True)
class _RefundServer:
    server: asyncio.AbstractServer
    idempotency_headers: list[str] = field(default_factory=list)
    authorization_headers: list[str] = field(default_factory=list)
    _effect_keys: set[str] = field(default_factory=set)

    @property
    def effect_count(self) -> int:
        return len(self._effect_keys)

    def record(self, headers: dict[str, str]) -> None:
        key = headers.get("x-idempotency-key", "")
        self.idempotency_headers.append(key)
        self.authorization_headers.append(headers.get("authorization", ""))
        if key:
            self._effect_keys.add(key)


async def _start_refund_server(
    *,
    cert_path: str,
    key_path: str,
) -> _RefundServer:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert_path, keyfile=key_path)
    refund_server: _RefundServer | None = None

    async def _handle(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        assert refund_server is not None
        try:
            headers = await _read_headers(reader)
            await _drain_body(reader, headers)
            refund_server.record(headers)
            body = b'{"refund":{"id":"provider-refund-1","status":"accepted"}}'
            writer.write(
                b"HTTP/1.1 201 Created\r\n"
                + f"Content-Length: {len(body)}\r\n".encode("ascii")
                + b"Content-Type: application/json\r\n\r\n"
                + body
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(
        _handle,
        "127.0.0.1",
        0,
        ssl=context,
    )
    refund_server = _RefundServer(server=server)
    return refund_server


async def _start_refund_server_or_skip(
    *,
    cert_path: str,
    key_path: str,
) -> _RefundServer:
    try:
        return await _start_refund_server(
            cert_path=cert_path,
            key_path=key_path,
        )
    except OSError as exc:
        if not os.environ.get("CI"):
            pytest.skip(f"loopback bind unavailable in sandbox: {exc}")
        raise


async def _invoke_socket_or_skip(coro: Any) -> Any:
    try:
        return await asyncio.wait_for(coro, timeout=5.0)
    except (OSError, TimeoutError) as exc:
        if not os.environ.get("CI"):
            pytest.skip(f"loopback connector call unavailable in sandbox: {exc}")
        raise


async def _read_headers(reader: asyncio.StreamReader) -> dict[str, str]:
    raw = await reader.readuntil(b"\r\n\r\n")
    lines = raw.decode("latin1").split("\r\n")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            continue
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return headers


async def _drain_body(
    reader: asyncio.StreamReader,
    headers: dict[str, str],
) -> None:
    raw_length = headers.get("content-length")
    if raw_length is None:
        return
    await reader.readexactly(int(raw_length))


def _generate_self_signed_cert(
    tmp_path: Path,
    hostname: str,
) -> tuple[str, str]:
    cert_path = tmp_path / f"{hostname}.crt"
    key_path = tmp_path / f"{hostname}.key"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-days",
            "1",
            "-nodes",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-subj",
            f"/CN={hostname}",
            "-addext",
            f"subjectAltName=DNS:{hostname}",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return str(cert_path), str(key_path)


def _server_port(server: asyncio.AbstractServer) -> int:
    sockets = server.sockets
    assert sockets is not None
    return int(sockets[0].getsockname()[1])


async def _close_server(server: asyncio.AbstractServer) -> None:
    server.close()
    await server.wait_closed()
