"""Stage 2: Generic connector + operations model break-control tests.

Verifies:
- Generic connector invocation with connector-id-scoped credentials
- Governance seam: act operation commitment_kind flows to Stage-1 gate
- Fail-closed: missing commitment_kind on act op → human
- Read operations bypass governance gate
- Validation: act op requires commitment_kind
- Existing connectors unaffected (separate test files, unchanged)
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.agents.capabilities import AgentCapability, CapabilitySet, ExecutionConstraints
from app.agents.context import AgentExecutionContext
from app.agents.enums import CapabilityScope
from app.agents.identity import AgentIdentity, ExecutionIdentity
from app.agents.results import ToolInvocationRequest
from app.agents.tools.connectors.config import (
    ConnectorConfigRecord,
    InMemoryConnectorConfigRepository,
)
from app.agents.tools.connectors.generic import (
    ConnectorDefinition,
    GenericConnectorTool,
    OperationDefinition,
    OperationMode,
    fail_closed_governance_check,
    validate_connector_definition,
)
from app.agents.tools.operation_metadata import (
    ApprovalPolicy,
    CommitmentKind,
    resolve_operation,
)
from app.agents.value_objects import CausalityMetadata
from app.core.ssrf import ValidatedPublicHTTPSURL

TENANT_ID = "tenant-generic-connector"
CONNECTOR_ID = "connector-alpha"
OPERATION_ID = "execute"
PROVIDER_KEY = "generic-idem-key-1"
CREDENTIAL_TOKEN = "generic-secret-token"


class _ConnectorCredentialRuntime:
    """In-memory credential runtime that resolves by connector_id."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def load_connector_credentials(
        self,
        *,
        tenant_id: str,
        connector_id: str,
    ) -> dict[str, Any]:
        self.calls.append((tenant_id, connector_id))
        return {"bearer_token": CREDENTIAL_TOKEN}


def _ssrf_validator(
    url: str,
    *,
    allowed_hosts: tuple[str, ...] = (),
) -> ValidatedPublicHTTPSURL:
    return ValidatedPublicHTTPSURL(
        url=url, hostname="api.example.com", port=443, pinned_ip="93.184.216.34"
    )


async def _config_repo(
    *,
    tool_name: str,
    endpoint_template: str = "https://api.example.com/v1/action",
    endpoint_host: str = "api.example.com",
) -> InMemoryConnectorConfigRepository:
    repo = InMemoryConnectorConfigRepository()
    await repo.save_config(
        ConnectorConfigRecord(
            tenant_id=TENANT_ID,
            connector_type="generic",
            tool_name=tool_name,
            http_method="POST",
            endpoint_template=endpoint_template,
            endpoint_host=endpoint_host,
            field_mappings={},
            idempotency_header_name="Idempotency-Key",
            response_parse={
                "provider_id": "id",
                "provider_status": "status",
            },
            success_status_codes=(200, 201, 202),
            status="active",
        ),
        expected_tenant_id=TENANT_ID,
    )
    return repo


def _context() -> AgentExecutionContext:
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="test-generic-agent",
            runtime_instance_id=uuid.uuid5(uuid.NAMESPACE_URL, "generic-agent"),
        ),
        execution=ExecutionIdentity(
            execution_id=uuid.uuid5(uuid.NAMESPACE_URL, "generic-exec"),
            request_id="generic-request",
        ),
        capabilities=CapabilitySet(
            (
                AgentCapability(
                    name="tool.generic.execute",
                    scope=CapabilityScope.INVOKE,
                ),
            )
        ),
        constraints=ExecutionConstraints(),
        causality=CausalityMetadata(),
        tenant_id=TENANT_ID,
        metadata={"session_id": "session-generic"},
    )


def _request(
    payload: dict[str, Any] | None = None,
    tool_name: str = f"{CONNECTOR_ID}.{OPERATION_ID}",
) -> ToolInvocationRequest:
    return ToolInvocationRequest(
        tool_name=tool_name,
        payload=payload or {"amount": 100},
        metadata={"agent_action_provider_idempotency_key": PROVIDER_KEY},
    )


# ─── Credential decoupling ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_credentials_resolve_by_connector_id_not_channel_enum() -> None:
    """Break-control (v): credentials resolve by connector_id."""
    credential_runtime = _ConnectorCredentialRuntime()
    operation = OperationDefinition(
        operation_id=OPERATION_ID,
        mode=OperationMode.ACT,
        commitment_kind=CommitmentKind.MONEY,
        approval_policy=ApprovalPolicy.TENANT_POLICY,
    )
    connector = ConnectorDefinition(
        connector_id=CONNECTOR_ID,
        protocol="https",
        operations=[operation],
    )
    tool_name = f"{CONNECTOR_ID}.{OPERATION_ID}"
    tool = GenericConnectorTool(
        connector=connector,
        operation=operation,
        config_repository=await _config_repo(tool_name=tool_name),
        credential_runtime=credential_runtime,
        ssrf_validator=_ssrf_validator,
    )

    assert tool.name == tool_name
    result = await tool.invoke(_request(), _context())
    assert credential_runtime.calls == [(TENANT_ID, CONNECTOR_ID)]
    assert result.status in ("success", "error")


# ─── Governance seam ─────────────────────────────────────────────────────────


def test_act_operation_governance_metadata_flows_to_stage1() -> None:
    """Break-control (iii): generic act op declaring commitment_kind=money
    routes through Stage-1 governance gate.
    """
    operation = OperationDefinition(
        operation_id="op.refund",
        mode=OperationMode.ACT,
        commitment_kind=CommitmentKind.MONEY,
        approval_policy=ApprovalPolicy.TENANT_POLICY,
        target_resource_expr="order:{order_id}",
    )
    metadata = operation.governance_metadata()
    assert metadata["operation_id"] == "op.refund"
    assert metadata["operation_commitment_kind"] == "money"
    assert metadata["operation_approval_policy"] == "tenant_policy"
    assert metadata["operation_target_resource_expr"] == "order:{order_id}"

    resolved = resolve_operation(metadata=metadata)
    assert resolved is not None
    assert resolved.commitment_kind is CommitmentKind.MONEY
    assert resolved.approval_policy is ApprovalPolicy.TENANT_POLICY


def test_act_operation_commitment_kind_goods_routes_to_human() -> None:
    """Break-control (iii): commitment_kind=goods routes to governance."""
    operation = OperationDefinition(
        operation_id="op.ship",
        mode=OperationMode.ACT,
        commitment_kind=CommitmentKind.GOODS,
        approval_policy=ApprovalPolicy.ALWAYS_REQUIRE_APPROVAL,
    )
    metadata = operation.governance_metadata()
    resolved = resolve_operation(metadata=metadata)
    assert resolved is not None
    assert resolved.commitment_kind is CommitmentKind.GOODS
    assert resolved.approval_policy is ApprovalPolicy.ALWAYS_REQUIRE_APPROVAL


# ─── Fail-closed ─────────────────────────────────────────────────────────────


def test_missing_commitment_kind_on_act_op_fails_closed() -> None:
    """Break-control (iv): missing commitment_kind on act op → human."""
    operation = OperationDefinition(
        operation_id="op.dangerous",
        mode=OperationMode.ACT,
        commitment_kind=None,
        approval_policy=ApprovalPolicy.TENANT_POLICY,
    )
    assert fail_closed_governance_check(operation) is True

    metadata = operation.governance_metadata()
    assert "operation_commitment_kind" not in metadata

    resolved = resolve_operation(metadata=metadata)
    assert resolved is not None
    assert resolved.commitment_kind is None


def test_unknown_commitment_kind_fails_closed_via_governance() -> None:
    """Break-control (iv): unknown commitment_kind → None → human."""
    metadata = {
        "operation_id": "op.unknown",
        "operation_commitment_kind": "totally_unknown_kind",
    }
    resolved = resolve_operation(metadata=metadata)
    assert resolved is not None
    assert resolved.commitment_kind is None


def test_read_operation_does_not_trigger_governance_check() -> None:
    """Read operations don't need governance gate."""
    operation = OperationDefinition(
        operation_id="op.query",
        mode=OperationMode.READ,
    )
    assert fail_closed_governance_check(operation) is False
    assert operation.requires_governance is False


# ─── Validation ──────────────────────────────────────────────────────────────


def test_connector_definition_validation_requires_commitment_kind_on_act() -> None:
    """Validation: act operation without commitment_kind is invalid."""
    connector = ConnectorDefinition(
        connector_id="c1",
        protocol="https",
        operations=[
            OperationDefinition(
                operation_id="op.safe",
                mode=OperationMode.READ,
            ),
            OperationDefinition(
                operation_id="op.dangerous",
                mode=OperationMode.ACT,
                commitment_kind=None,
            ),
        ],
    )
    errors = validate_connector_definition(connector)
    assert any("commitment_kind" in e for e in errors)


def test_connector_definition_validation_passes_for_well_formed() -> None:
    """Well-formed definitions pass validation."""
    connector = ConnectorDefinition(
        connector_id="c2",
        protocol="https",
        operations=[
            OperationDefinition(
                operation_id="op.read",
                mode=OperationMode.READ,
            ),
            OperationDefinition(
                operation_id="op.act",
                mode=OperationMode.ACT,
                commitment_kind=CommitmentKind.RECORD_UPDATE,
                approval_policy=ApprovalPolicy.TENANT_POLICY,
            ),
        ],
    )
    errors = validate_connector_definition(connector)
    assert errors == []


def test_connector_definition_rejects_duplicate_operation_ids() -> None:
    connector = ConnectorDefinition(
        connector_id="c3",
        protocol="https",
        operations=[
            OperationDefinition(
                operation_id="op.dup",
                mode=OperationMode.READ,
            ),
            OperationDefinition(
                operation_id="op.dup",
                mode=OperationMode.ACT,
                commitment_kind=CommitmentKind.MONEY,
            ),
        ],
    )
    errors = validate_connector_definition(connector)
    assert any("duplicate" in e for e in errors)


# ─── Domain-agnostic guard ───────────────────────────────────────────────────


def test_generic_connector_model_names_no_vendors_or_domains() -> None:
    """Break-control (vi): the connector/operations/credential layer names
    no vendors/domains/business-actions in code (registry/data exception).

    Import paths are excluded (reusing existing utilities from the refund
    module is code reuse, not domain naming in the model itself).
    """
    import re
    import inspect
    import app.agents.tools.connectors.generic as module

    source = inspect.getsource(module)
    # Strip import lines — those reference existing module paths, not model naming
    non_import_lines = [
        line for line in source.splitlines()
        if not line.strip().startswith(("from ", "import "))
    ]
    filtered_source = "\n".join(non_import_lines)

    vendor_terms = [
        "shopify", "zendesk", "stripe", "paypal", "amazon",
        "google", "whatsapp", "slack", "jira", "linear",
    ]
    for term in vendor_terms:
        pattern = rf"\b{re.escape(term)}\b"
        assert not re.search(pattern, filtered_source, re.IGNORECASE), (
            f"generic connector module must not reference vendor: {term}"
        )

    business_terms = ["refund", "warranty", "replacement", "inventory", "shipping"]
    for term in business_terms:
        pattern = rf"\b{re.escape(term)}\b"
        assert not re.search(pattern, filtered_source, re.IGNORECASE), (
            f"generic connector module must not reference business action: {term}"
        )


# ─── Connector lookup ────────────────────────────────────────────────────────


def test_connector_definition_get_operation() -> None:
    op_read = OperationDefinition(operation_id="read", mode=OperationMode.READ)
    op_act = OperationDefinition(
        operation_id="act",
        mode=OperationMode.ACT,
        commitment_kind=CommitmentKind.MONEY,
    )
    connector = ConnectorDefinition(
        connector_id="c4",
        protocol="https",
        operations=[op_read, op_act],
    )
    assert connector.get_operation("read") is op_read
    assert connector.get_operation("act") is op_act
    assert connector.get_operation("nonexistent") is None


# ─── Tool name composition ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_channel_bridged_credential_runtime_resolves_by_connector_id() -> None:
    """The bridge adapter resolves credentials via existing channel infra."""
    from app.agents.tools.connectors.generic import (
        ChannelBridgedConnectorCredentialRuntime,
    )
    from app.tenant.enums import TenantChannelType

    class _MockChannelLoader:
        async def load_channel_credentials(
            self, *, tenant_id: str, channel_type: TenantChannelType
        ) -> dict[str, Any]:
            return {"bearer_token": f"token-for-{channel_type.value}"}

    bridge = ChannelBridgedConnectorCredentialRuntime(
        channel_credential_loader=_MockChannelLoader(),
        connector_channel_map={"my-connector": TenantChannelType.OMS},
    )
    result = await bridge.load_connector_credentials(
        tenant_id="t1", connector_id="my-connector"
    )
    assert result == {"bearer_token": "token-for-oms"}


@pytest.mark.asyncio
async def test_channel_bridged_credential_runtime_fails_for_unknown_connector() -> None:
    """Unknown connector_id raises ConnectorConfigError."""
    from app.agents.tools.connectors.generic import (
        ChannelBridgedConnectorCredentialRuntime,
    )
    from app.agents.tools.connectors.config import ConnectorConfigError

    bridge = ChannelBridgedConnectorCredentialRuntime(
        channel_credential_loader=None,
        connector_channel_map={},
    )
    with pytest.raises(ConnectorConfigError, match="no credential binding"):
        await bridge.load_connector_credentials(
            tenant_id="t1", connector_id="unknown"
        )


def test_tool_name_is_connector_dot_operation() -> None:
    """Tool name is composed as connector_id.operation_id."""
    op = OperationDefinition(
        operation_id="execute",
        mode=OperationMode.ACT,
        commitment_kind=CommitmentKind.NONE,
    )
    connector = ConnectorDefinition(
        connector_id="my-connector",
        protocol="https",
        operations=[op],
    )
    tool = GenericConnectorTool(
        connector=connector,
        operation=op,
        config_repository=InMemoryConnectorConfigRepository(),
        credential_runtime=_ConnectorCredentialRuntime(),
    )
    assert tool.name == "my-connector.execute"
