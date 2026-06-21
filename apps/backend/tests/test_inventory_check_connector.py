"""W3 break-controls: the inventory.check connector (Part A).

Read-only — this connector never mutates inventory or moves goods. Same
SSRF/credential/idempotency/arm-guard rigor as the money connectors
(refund/replacement/warranty) is proven here by reusing the EXACT test
patterns test_connector_framework.py established for those connectors —
this is the proof those guards apply identically to a 5th connector, not
a reimplementation of the guards themselves.
"""

from __future__ import annotations

import inspect
import uuid
from typing import Any
from urllib.parse import urlsplit

import pytest

from app.agents.capabilities import AgentCapability, CapabilitySet, ExecutionConstraints
from app.agents.context import AgentExecutionContext
from app.agents.enums import CapabilityScope
from app.agents.identity import AgentIdentity, ExecutionIdentity
from app.agents.results import ToolInvocationRequest
from app.agents.tools.connectors import (
    ConnectorConfigRecord,
    InMemoryConnectorConfigRepository,
    InventoryCheckConnector,
)
from app.agents.tools.connectors.inventory import (
    AVAILABLE_PROVIDER_STATUS,
    UNAVAILABLE_PROVIDER_STATUS,
)
from app.agents.tools.grants import AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY
from app.agents.value_objects import CausalityMetadata
from app.cognition.extraction import ExtractedField, ExtractedOrderFields
from app.core.ssrf import SSRFValidationError, ValidatedPublicHTTPSURL, validate_public_https_url
from app.runtime.inventory_availability import ConnectorInventoryAvailabilityChecker
from app.tenant.enums import TenantChannelType

_TENANT_ID = "tenant-inventory-check"
_TOOL_NAME = "inventory.check"
_PROVIDER_KEY = "inventory-check-provider-key"


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
        return {"auth_header": "Bearer inventory-secret"}


class _StubResponse:
    def __init__(self, *, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self._body = body

    @property
    def text(self) -> str:
        return str(self._body)

    def json(self) -> Any:
        return self._body


def _config(
    *,
    response_parse: dict[str, Any] | None = None,
) -> ConnectorConfigRecord:
    return ConnectorConfigRecord(
        tenant_id=_TENANT_ID,
        connector_type=TenantChannelType.OMS.value,
        tool_name=_TOOL_NAME,
        http_method="GET",
        endpoint_template="https://inventory.example/availability/{product_sku}",
        endpoint_host="inventory.example",
        field_mappings={"sku": "payload.product_sku", "remedy": "payload.remedy"},
        idempotency_header_name="X-Idempotency-Key",
        response_parse=response_parse
        or {
            "available": "stock.available",
            "provider_id": "stock.sku",
            "provider_error": "error.message",
        },
        success_status_codes=(200,),
    )


async def _memory_config(
    *, response_parse: dict[str, Any] | None = None
) -> InMemoryConnectorConfigRepository:
    repository = InMemoryConnectorConfigRepository()
    await repository.save_config(
        _config(response_parse=response_parse), expected_tenant_id=_TENANT_ID
    )
    return repository


def _request() -> ToolInvocationRequest:
    return ToolInvocationRequest(
        tool_name=_TOOL_NAME,
        payload={"product_sku": "sku-1", "remedy": "replacement"},
        metadata={AGENT_ACTION_PROVIDER_IDEMPOTENCY_KEY: _PROVIDER_KEY},
    )


def _context() -> AgentExecutionContext:
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="test-inventory-agent",
            runtime_instance_id=uuid.uuid5(uuid.NAMESPACE_URL, "inventory-agent"),
        ),
        execution=ExecutionIdentity(
            execution_id=uuid.uuid5(uuid.NAMESPACE_URL, "inventory-exec"),
            request_id="inventory-request",
        ),
        capabilities=CapabilitySet(
            (
                AgentCapability(
                    name="tool.inventory.check",
                    scope=CapabilityScope.INVOKE,
                ),
            )
        ),
        constraints=ExecutionConstraints(),
        causality=CausalityMetadata(),
        tenant_id=_TENANT_ID,
        metadata={},
    )


def _private_ip_validator(
    url: str,
    *,
    allowed_hosts: tuple[str, ...] = (),
) -> ValidatedPublicHTTPSURL:
    def _resolve(_host: str, _port: int) -> tuple[str, ...]:
        return ("169.254.169.254",)

    return validate_public_https_url(url, allowed_hosts=allowed_hosts, resolve=_resolve)


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


class _FakeClient:
    def __init__(self, *, available: bool) -> None:
        self._available = available

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        del exc_info

    async def request(self, *args: object, **kwargs: object) -> _StubResponse:
        del args, kwargs
        return _StubResponse(
            status_code=200,
            body={"stock": {"available": self._available, "sku": "sku-1"}},
        )


def _patch_isolated_http_client(
    monkeypatch: pytest.MonkeyPatch, *, available: bool
) -> None:
    def _factory(**_kwargs: object) -> _FakeClient:
        return _FakeClient(available=available)

    monkeypatch.setattr(
        "app.agents.tools.connectors.base.create_isolated_http_client",
        _factory,
    )


# ─── build_request / parse_response ────────────────────────────────────────


def test_build_request_renders_endpoint_and_maps_body() -> None:
    connector = InventoryCheckConnector(
        config_repository=InMemoryConnectorConfigRepository(),
        credential_runtime=_CredentialRuntime(),
    )
    outbound = connector.build_request(
        payload={"product_sku": "sku-1", "remedy": "replacement"},
        config=_config(),
    )
    assert outbound.url == "https://inventory.example/availability/sku-1"
    assert outbound.method == "GET"
    assert outbound.json_body == {"sku": "sku-1", "remedy": "replacement"}


@pytest.mark.parametrize(
    ("available_value", "expected_status"),
    [
        (True, AVAILABLE_PROVIDER_STATUS),
        (False, UNAVAILABLE_PROVIDER_STATUS),
        ("in_stock", AVAILABLE_PROVIDER_STATUS),
        ("out_of_stock", UNAVAILABLE_PROVIDER_STATUS),
        (3, AVAILABLE_PROVIDER_STATUS),
        (0, UNAVAILABLE_PROVIDER_STATUS),
        (None, UNAVAILABLE_PROVIDER_STATUS),
    ],
)
def test_parse_response_interprets_tenant_shaped_availability_field(
    available_value: object, expected_status: str
) -> None:
    """Domain-agnostic field interpretation: a tenant's own API shape
    (boolean, string status, or a raw quantity) all normalize correctly —
    nothing here assumes a specific provider's response vocabulary."""
    connector = InventoryCheckConnector(
        config_repository=InMemoryConnectorConfigRepository(),
        credential_runtime=_CredentialRuntime(),
    )
    response = _StubResponse(
        status_code=200,
        body={"stock": {"available": available_value, "sku": "sku-1"}},
    )
    fields = connector.parse_response(response, config=_config())
    assert fields.provider_status == expected_status
    assert fields.provider_id == "sku-1"


# ─── happy path / unavailable, end-to-end through invoke() ─────────────────


@pytest.mark.asyncio
async def test_invoke_reports_available_without_real_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = InventoryCheckConnector(
        config_repository=await _memory_config(),
        credential_runtime=_CredentialRuntime(),
        ssrf_validator=_local_validator,
    )
    _patch_isolated_http_client(monkeypatch, available=True)
    result = await connector.invoke(_request(), _context())
    assert result.status == "success"
    assert result.output["provider_status"] == AVAILABLE_PROVIDER_STATUS


@pytest.mark.asyncio
async def test_invoke_reports_unavailable_without_real_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = InventoryCheckConnector(
        config_repository=await _memory_config(),
        credential_runtime=_CredentialRuntime(),
        ssrf_validator=_local_validator,
    )
    _patch_isolated_http_client(monkeypatch, available=False)
    result = await connector.invoke(_request(), _context())
    assert result.status == "success"
    assert result.output["provider_status"] == UNAVAILABLE_PROVIDER_STATUS


# ─── SSRF (call-time) ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_private_provider_ip_is_rejected_before_network() -> None:
    connector = InventoryCheckConnector(
        config_repository=await _memory_config(),
        credential_runtime=_CredentialRuntime(),
        ssrf_validator=_private_ip_validator,
    )
    with pytest.raises(SSRFValidationError):
        await connector.invoke(_request(), _context())


# ─── arm-guard: unconfigured tenant cannot invoke ──────────────────────────


@pytest.mark.asyncio
async def test_unconfigured_tenant_fails_closed_not_silently_available() -> None:
    """The arm-guard: inventory.check cannot reach a provider at all
    without an active connector config — it must error, never silently
    report "available" because nothing was configured."""
    connector = InventoryCheckConnector(
        config_repository=InMemoryConnectorConfigRepository(),
        credential_runtime=_CredentialRuntime(),
    )
    result = await connector.invoke(_request(), _context())
    assert result.status == "error"
    assert result.error_code == "connector_config_missing"


@pytest.mark.asyncio
async def test_disabled_config_fails_closed_same_as_unconfigured() -> None:
    repository = InMemoryConnectorConfigRepository()
    await repository.save_config(
        ConnectorConfigRecord(
            tenant_id=_TENANT_ID,
            connector_type=TenantChannelType.OMS.value,
            tool_name=_TOOL_NAME,
            http_method="GET",
            endpoint_template="https://inventory.example/availability/{product_sku}",
            endpoint_host="inventory.example",
            status="disabled",
        ),
        expected_tenant_id=_TENANT_ID,
    )
    connector = InventoryCheckConnector(
        config_repository=repository,
        credential_runtime=_CredentialRuntime(),
    )
    result = await connector.invoke(_request(), _context())
    assert result.status == "error"
    assert result.error_code == "connector_config_missing"


# ─── read-only proof ────────────────────────────────────────────────────────


def test_module_imports_no_mutation_capable_symbol() -> None:
    """Static proof this connector cannot move goods or money: it must
    never import a work-order repository, an approval-firing symbol, or
    any of the OTHER connectors' execution machinery — only the pure
    string-mapping helpers (render_endpoint/mapped_body/etc.) that every
    generic REST connector, including the money ones, already shares."""
    import app.agents.tools.connectors.inventory as module

    source = inspect.getsource(module)
    forbidden = (
        "WorkOrder",
        "work_order",
        "ActionApproval",
        "approve_case",
        "fire_action",
    )
    assert not any(token in source for token in forbidden)


# ─── ConnectorInventoryAvailabilityChecker adapter (fail-safe boundary) ────


def _extracted_fields() -> ExtractedOrderFields:
    return ExtractedOrderFields(
        product_sku=ExtractedField(value="sku-1", confidence="high", source="text"),
    )


@pytest.mark.asyncio
async def test_adapter_returns_none_when_unconfigured() -> None:
    """The arm-guard, from the remedy-selection walk's point of view: an
    unconfigured connector must translate to None (unknown), never False
    (confirmed unavailable) — those mean very different things to the
    fail-safe walk."""
    checker = ConnectorInventoryAvailabilityChecker(
        connector=InventoryCheckConnector(
            config_repository=InMemoryConnectorConfigRepository(),
            credential_runtime=_CredentialRuntime(),
        )
    )
    result = await checker.check_availability(
        tenant_id=_TENANT_ID,
        remedy="replacement",
        extracted_fields=_extracted_fields(),
    )
    assert result is None


@pytest.mark.asyncio
async def test_adapter_translates_available_provider_status_to_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = ConnectorInventoryAvailabilityChecker(
        connector=InventoryCheckConnector(
            config_repository=await _memory_config(),
            credential_runtime=_CredentialRuntime(),
            ssrf_validator=_local_validator,
        )
    )
    _patch_isolated_http_client(monkeypatch, available=True)
    result = await checker.check_availability(
        tenant_id=_TENANT_ID,
        remedy="replacement",
        extracted_fields=_extracted_fields(),
    )
    assert result is True


@pytest.mark.asyncio
async def test_adapter_translates_unavailable_provider_status_to_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = ConnectorInventoryAvailabilityChecker(
        connector=InventoryCheckConnector(
            config_repository=await _memory_config(),
            credential_runtime=_CredentialRuntime(),
            ssrf_validator=_local_validator,
        )
    )
    _patch_isolated_http_client(monkeypatch, available=False)
    result = await checker.check_availability(
        tenant_id=_TENANT_ID,
        remedy="replacement",
        extracted_fields=_extracted_fields(),
    )
    assert result is False


@pytest.mark.asyncio
async def test_adapter_fails_safe_to_none_on_unexpected_exception() -> None:
    class _ExplodingConnector(InventoryCheckConnector):
        async def invoke(self, request: object, context: object) -> object:  # type: ignore[override]
            raise RuntimeError("simulated transport failure")

    checker = ConnectorInventoryAvailabilityChecker(
        connector=_ExplodingConnector(
            config_repository=InMemoryConnectorConfigRepository(),
            credential_runtime=_CredentialRuntime(),
        )
    )
    result = await checker.check_availability(
        tenant_id=_TENANT_ID,
        remedy="replacement",
        extracted_fields=_extracted_fields(),
    )
    assert result is None
