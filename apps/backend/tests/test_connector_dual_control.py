"""PR 3 break-control tests: dual-control + SSRF on connector config.

Deliverables:
#3  SSRF config-time: 169.254.169.254 and RFC1918 endpoint → rejected at propose
#4  SSRF call-time: private host → SSRFValidationError, NO HTTP connection;
    negative control with bypassed guard proves connection WOULD be attempted
#5  Credential-in-config: credential key in payload → rejected at propose
#6  Dual-control: same proposer/approver → TenantConfigChangeRequestSeparationError;
    different approver → succeeds
    Capability gating: missing tenant.connector.write → 403;
                       missing tenant.connector.approve → 403
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlsplit

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.agents.context import AgentExecutionContext
from app.agents.capabilities import AgentCapability, CapabilitySet, ExecutionConstraints
from app.agents.enums import CapabilityScope
from app.agents.identity import AgentIdentity, ExecutionIdentity
from app.agents.results import ToolInvocationRequest
from app.agents.tools.connectors import (
    ConnectorConfigRecord,
    GenericRestRefundConnector,
    InMemoryConnectorConfigRepository,
)
from app.agents.tools.grants import AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY
from app.agents.value_objects import CausalityMetadata
from app.api.v1.routers.tenant import (
    _require_change_request_domain_capability,
    _require_change_request_approve_capability,
)
from app.core.ssrf import (
    SSRFValidationError,
    ValidatedPublicHTTPSURL,
    validate_public_https_url,
)
from app.dependencies.authority import (
    TENANT_CONNECTOR_APPROVE_CAPABILITY,
    TENANT_CONNECTOR_WRITE_CAPABILITY,
    ERROR_CODE_CAPABILITY_REQUIRED,
)
from app.identity import AuthorityContext
from app.services.tenant_config_change_request_service import (
    TenantConfigChangeRequestService,
)
from app.tenant.change_requests import (
    TenantConfigChangeRequestRecord,
    TenantConfigChangeRequestSeparationError,
    TenantConfigChangeRequestStatus,
    TenantConfigChangeType,
)
from app.tenant.enums import TenantChannelType

# ─── constants ────────────────────────────────────────────────────────────────

_TENANT = "tenant-dc-tests"
_TOOL_NAME = "refund.request"
_PROVIDER_KEY = "dc-provider-key"

_VALID_CONNECTOR_PAYLOAD: dict[str, Any] = {
    "connector_type": TenantChannelType.OMS.value,
    "tool_name": _TOOL_NAME,
    "http_method": "POST",
    "endpoint_template": "https://api.example.com/v1/refunds",
    "endpoint_host": "api.example.com",
    "field_mappings": {},
    "response_parse": {},
    "idempotency_header_name": "Idempotency-Key",
    "success_status_codes": [200, 201],
}


# ─── helpers ──────────────────────────────────────────────────────────────────


@dataclass
class _MockRepository:
    """In-memory repository for service-layer break-control tests."""

    _store: list[TenantConfigChangeRequestRecord] = field(default_factory=list)

    async def create(
        self,
        record: TenantConfigChangeRequestRecord,
        *,
        expected_tenant_id: str,
    ) -> TenantConfigChangeRequestRecord:
        self._store.append(record)
        return record

    async def get(
        self,
        change_request_id: uuid.UUID,
        *,
        expected_tenant_id: str,
    ) -> TenantConfigChangeRequestRecord | None:
        for r in self._store:
            if r.change_request_id == change_request_id:
                return r
        return None

    async def list(self, **_: Any) -> Any:  # noqa: ANN401
        raise NotImplementedError

    async def update(
        self,
        record: TenantConfigChangeRequestRecord,
        *,
        expected_tenant_id: str,
    ) -> TenantConfigChangeRequestRecord:
        self._store = [
            record if r.change_request_id == record.change_request_id else r
            for r in self._store
        ]
        return record


def _make_service(repo: _MockRepository) -> TenantConfigChangeRequestService:
    session = MagicMock()
    session.commit = AsyncMock()
    event_appender = MagicMock()
    event_appender.append_event = AsyncMock()
    tenant_config_svc = MagicMock()
    return TenantConfigChangeRequestService(
        repository=repo,
        tenant_configuration_service=tenant_config_svc,
        event_appender=event_appender,
        session=session,
    )


def _mock_request(capabilities: list[str]) -> Request:
    ctx = AuthorityContext(
        tenant_id=_TENANT,
        principal_id="principal-1",
        capabilities=tuple(capabilities),
    )
    scope = {"type": "http", "headers": []}
    req = Request(scope)
    req.state.authority = ctx
    return req


def _connector_config(
    endpoint_template: str = "https://api.example.com/v1/refunds",
    endpoint_host: str = "api.example.com",
) -> ConnectorConfigRecord:
    return ConnectorConfigRecord(
        tenant_id=_TENANT,
        connector_type=TenantChannelType.OMS.value,
        tool_name=_TOOL_NAME,
        http_method="POST",
        endpoint_template=endpoint_template,
        endpoint_host=endpoint_host,
        field_mappings={},
        response_parse={},
        idempotency_header_name="Idempotency-Key",
        success_status_codes=(200, 201),
    )


async def _memory_repo(
    endpoint_template: str = "https://api.example.com/v1/refunds",
    endpoint_host: str = "api.example.com",
) -> InMemoryConnectorConfigRepository:
    repo = InMemoryConnectorConfigRepository()
    await repo.save_config(
        _connector_config(
            endpoint_template=endpoint_template,
            endpoint_host=endpoint_host,
        ),
        expected_tenant_id=_TENANT,
    )
    return repo


class _NullCredentialRuntime:
    async def load_channel_credentials(
        self, *, tenant_id: str, channel_type: TenantChannelType
    ) -> dict[str, Any]:
        return {"auth_header": "Bearer test-token"}


def _invocation_request() -> ToolInvocationRequest:
    return ToolInvocationRequest(
        tool_name=_TOOL_NAME,
        payload={
            "order_id": "order-x",
            "product_sku": "sku-x",
            "refund_amount_cents": 500,
            "refund_reason": "duplicate",
        },
        metadata={
            "session_id": "session-dc",
            "target_resource": "order:order-x",
            "tool_name": _TOOL_NAME,
            AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY: _PROVIDER_KEY,
        },
    )


def _execution_context() -> AgentExecutionContext:
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="dc-test-agent",
            runtime_instance_id=uuid.uuid5(uuid.NAMESPACE_URL, "dc-agent"),
        ),
        execution=ExecutionIdentity(
            execution_id=uuid.uuid5(uuid.NAMESPACE_URL, "dc-exec"),
            request_id="dc-request",
        ),
        capabilities=CapabilitySet(
            (AgentCapability(name="tool.refund.request", scope=CapabilityScope.INVOKE),)
        ),
        constraints=ExecutionConstraints(),
        causality=CausalityMetadata(),
        tenant_id=_TENANT,
        metadata={"session_id": "session-dc"},
    )


def _private_ip_validator(
    url: str,
    *,
    allowed_hosts: tuple[str, ...] = (),
) -> ValidatedPublicHTTPSURL:
    def _resolve(_host: str, _port: int) -> tuple[str, ...]:
        return ("10.0.0.1",)

    return validate_public_https_url(url, allowed_hosts=allowed_hosts, resolve=_resolve)


def _passthrough_validator(
    url: str,
    *,
    allowed_hosts: tuple[str, ...] = (),
) -> ValidatedPublicHTTPSURL:
    parsed = urlsplit(url)
    return ValidatedPublicHTTPSURL(
        url=url,
        hostname=parsed.hostname or "",
        port=parsed.port or 443,
        pinned_ip="10.0.0.1",
    )


# ─── break-control #3: SSRF config-time ───────────────────────────────────────


@pytest.mark.asyncio
async def test_ssrf_config_time_link_local_metadata_rejected() -> None:
    """169.254.169.254 (cloud metadata endpoint) rejected at propose time."""
    service = _make_service(_MockRepository())
    bad_payload = {
        **_VALID_CONNECTOR_PAYLOAD,
        "endpoint_host": "169.254.169.254",
        "endpoint_template": "https://169.254.169.254/latest/meta-data/",
    }
    with pytest.raises(Exception, match="private or reserved"):
        await service.propose(
            tenant_id=_TENANT,
            change_type=TenantConfigChangeType.CONNECTOR,
            payload=bad_payload,
            proposed_by="alice",
        )


@pytest.mark.asyncio
async def test_ssrf_config_time_rfc1918_rejected() -> None:
    """RFC1918 private IP endpoint rejected at propose time."""
    service = _make_service(_MockRepository())
    bad_payload = {
        **_VALID_CONNECTOR_PAYLOAD,
        "endpoint_host": "192.168.1.100",
        "endpoint_template": "https://192.168.1.100/api/refunds",
    }
    with pytest.raises(Exception, match="private or reserved"):
        await service.propose(
            tenant_id=_TENANT,
            change_type=TenantConfigChangeType.CONNECTOR,
            payload=bad_payload,
            proposed_by="alice",
        )


@pytest.mark.asyncio
async def test_ssrf_config_time_loopback_rejected() -> None:
    """Loopback IP endpoint rejected at propose time."""
    service = _make_service(_MockRepository())
    bad_payload = {
        **_VALID_CONNECTOR_PAYLOAD,
        "endpoint_host": "127.0.0.1",
        "endpoint_template": "https://127.0.0.1/api/refunds",
    }
    with pytest.raises(Exception, match="private or reserved"):
        await service.propose(
            tenant_id=_TENANT,
            change_type=TenantConfigChangeType.CONNECTOR,
            payload=bad_payload,
            proposed_by="alice",
        )


# ─── break-control #4: SSRF call-time + negative control ──────────────────────


@pytest.mark.asyncio
async def test_ssrf_call_time_private_host_raises_ssrf_error() -> None:
    """With real SSRF guard, a host resolving to 10.x raises SSRFValidationError.
    asyncio.open_connection is never reached.
    """
    connection_attempts: list[tuple[str, int]] = []

    async def _spy_connect(host: str, port: int, **_: Any) -> None:
        connection_attempts.append((host, port))
        raise OSError(111, "Connection refused (spy)")

    connector = GenericRestRefundConnector(
        config_repository=await _memory_repo(),
        credential_runtime=_NullCredentialRuntime(),
        ssrf_validator=_private_ip_validator,
    )

    original_open = asyncio.open_connection
    asyncio.open_connection = _spy_connect  # type: ignore[assignment]
    try:
        with pytest.raises(SSRFValidationError):
            await connector.invoke(_invocation_request(), _execution_context())
    finally:
        asyncio.open_connection = original_open

    assert connection_attempts == [], (
        "asyncio.open_connection was called even though SSRFValidationError "
        "should have aborted before any network contact"
    )


@pytest.mark.asyncio
async def test_ssrf_call_time_negative_control_bypassed_guard_connects() -> None:
    """Negative control: with guard bypassed, asyncio.open_connection IS called.

    This proves the SSRF guard (not some other layer) is what blocks the
    connection in the real test above.
    """
    connection_attempts: list[tuple[str, int]] = []

    async def _spy_connect(host: str, port: int, **_: Any) -> None:
        connection_attempts.append((host, port))
        raise OSError(111, "Connection refused (spy)")

    connector = GenericRestRefundConnector(
        config_repository=await _memory_repo(),
        credential_runtime=_NullCredentialRuntime(),
        ssrf_validator=_passthrough_validator,
    )

    original_open = asyncio.open_connection
    asyncio.open_connection = _spy_connect  # type: ignore[assignment]
    try:
        exc: BaseException | None = None
        try:
            await connector.invoke(_invocation_request(), _execution_context())
        except Exception as e:
            exc = e
    finally:
        asyncio.open_connection = original_open

    assert connection_attempts, (
        "asyncio.open_connection was NOT called with bypassed SSRF guard — "
        "the negative control is broken"
    )
    assert not isinstance(exc, SSRFValidationError), (
        "SSRFValidationError raised with bypassed guard — "
        "the SSRF validator was not actually bypassed"
    )
    assert connection_attempts[0][0] == "10.0.0.1", (
        f"expected connection to pinned IP 10.0.0.1; got {connection_attempts[0]}"
    )


# ─── break-control #5: credential-in-config rejection ─────────────────────────


@pytest.mark.parametrize(
    "credential_key",
    [
        "api_key",
        "bearer_token",
        "access_token",
        "webhook_secret",
        "credentials_enc",
    ],
)
@pytest.mark.asyncio
async def test_credential_key_in_connector_payload_rejected(
    credential_key: str,
) -> None:
    """Credential fields in a connector config payload → rejected at propose."""
    service = _make_service(_MockRepository())
    bad_payload = {
        **_VALID_CONNECTOR_PAYLOAD,
        credential_key: "should-not-be-here",
    }
    with pytest.raises(Exception, match="credential"):
        await service.propose(
            tenant_id=_TENANT,
            change_type=TenantConfigChangeType.CONNECTOR,
            payload=bad_payload,
            proposed_by="alice",
        )


# ─── break-control #6: dual-control ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_dual_control_same_proposer_approver_rejected() -> None:
    """Propose then approve with the SAME principal → TenantConfigChangeRequestSeparationError."""
    repo = _MockRepository()
    service = _make_service(repo)

    proposed = await service.propose(
        tenant_id=_TENANT,
        change_type=TenantConfigChangeType.CONNECTOR,
        payload=_VALID_CONNECTOR_PAYLOAD,
        proposed_by="alice",
    )
    assert proposed.status is TenantConfigChangeRequestStatus.PROPOSED
    assert proposed.proposed_by == "alice"

    with pytest.raises(TenantConfigChangeRequestSeparationError):
        await service.approve(
            change_request_id=proposed.change_request_id,
            approved_by="alice",
            expected_tenant_id=_TENANT,
        )


@pytest.mark.asyncio
async def test_dual_control_different_approver_succeeds() -> None:
    """Propose by alice, approve by bob → APPROVED status."""
    repo = _MockRepository()
    service = _make_service(repo)

    proposed = await service.propose(
        tenant_id=_TENANT,
        change_type=TenantConfigChangeType.CONNECTOR,
        payload=_VALID_CONNECTOR_PAYLOAD,
        proposed_by="alice",
    )
    approved = await service.approve(
        change_request_id=proposed.change_request_id,
        approved_by="bob",
        expected_tenant_id=_TENANT,
    )
    assert approved.status is TenantConfigChangeRequestStatus.APPROVED
    assert approved.approved_by == "bob"
    assert approved.proposed_by == "alice"


# ─── break-control capability gating ──────────────────────────────────────────


def test_propose_missing_connector_write_raises_403() -> None:
    """Missing tenant.connector.write → 403 on connector config propose."""
    req = _mock_request(["tenant.config.approve"])  # has approve but NOT write
    with pytest.raises(HTTPException) as exc_info:
        _require_change_request_domain_capability(
            change_type=TenantConfigChangeType.CONNECTOR,
            authority=req.state.authority,
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == ERROR_CODE_CAPABILITY_REQUIRED
    assert exc_info.value.detail["capability"] == TENANT_CONNECTOR_WRITE_CAPABILITY


def test_propose_with_connector_write_passes() -> None:
    """Having tenant.connector.write → no exception on propose capability check."""
    req = _mock_request([TENANT_CONNECTOR_WRITE_CAPABILITY])
    _require_change_request_domain_capability(
        change_type=TenantConfigChangeType.CONNECTOR,
        authority=req.state.authority,
    )


def test_approve_missing_connector_approve_raises_403() -> None:
    """Missing tenant.connector.approve → 403 on connector config approve."""
    req = _mock_request([TENANT_CONNECTOR_WRITE_CAPABILITY])  # write but NOT approve
    with pytest.raises(HTTPException) as exc_info:
        _require_change_request_approve_capability(
            change_type=TenantConfigChangeType.CONNECTOR,
            authority=req.state.authority,
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == ERROR_CODE_CAPABILITY_REQUIRED
    assert exc_info.value.detail["capability"] == TENANT_CONNECTOR_APPROVE_CAPABILITY


def test_approve_with_connector_approve_passes() -> None:
    """Having tenant.connector.approve → no exception on approve capability check."""
    req = _mock_request([TENANT_CONNECTOR_APPROVE_CAPABILITY])
    _require_change_request_approve_capability(
        change_type=TenantConfigChangeType.CONNECTOR,
        authority=req.state.authority,
    )


def test_approve_non_connector_uses_generic_capability() -> None:
    """Non-connector change types still use the generic tenant.config.approve."""
    from app.dependencies.authority import TENANT_CONFIG_APPROVE_CAPABILITY

    req = _mock_request([TENANT_CONFIG_APPROVE_CAPABILITY])
    _require_change_request_approve_capability(
        change_type=TenantConfigChangeType.KNOWLEDGE,
        authority=req.state.authority,
    )

    req_missing = _mock_request([TENANT_CONNECTOR_APPROVE_CAPABILITY])
    with pytest.raises(HTTPException) as exc_info:
        _require_change_request_approve_capability(
            change_type=TenantConfigChangeType.KNOWLEDGE,
            authority=req_missing.state.authority,
        )
    assert exc_info.value.detail["capability"] == TENANT_CONFIG_APPROVE_CAPABILITY
